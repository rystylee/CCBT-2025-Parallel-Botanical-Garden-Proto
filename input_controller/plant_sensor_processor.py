#!/usr/bin/env python3
"""植物センサー → soft_prefix → Mac(10.0.0.202) 配信
                + /mixer → RunPod JSON送信

AE×CF 2軸マトリクスで soft_prefix の「揺らぎの性格」を決定する。
全状態がLLMに強い影響を与える設計。植物が静かでも活発でも、
生成される詩のトーンが植物の状態に連動して変化する。

/mixer 受信分は ubuntu_sender.py と同等のバッファリング＋SCP転送を行う。

=== マトリクス ===
               CF悪化(<-0.3)  CF安定(-0.3~0.3)  CF良化(>0.3)
  AE低(<0.33)    1e-3(収束的)    3e-3              7e-3
  AE中(0.33~0.66) 3e-3           7e-3              1e-2
  AE高(>0.66)    7e-3            1e-2              1e-2(発散的)

使い方:
    python3 plant_sensor_processor.py
    python3 plant_sensor_processor.py --config path/to/plant_sensor_config.json
    python3 plant_sensor_processor.py --dry-run
    python3 plant_sensor_processor.py --no-runpod   # RunPod送信を無効化
"""

import argparse
import asyncio
import csv
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient
from pythonosc import osc_message_builder

import base64
import struct

SP_P = 1
SP_H = 1536

CF_PFI_PATTERN = re.compile(r"^/(CF\d+)/pfi$", re.IGNORECASE)
CF_ANY_PATTERN = re.compile(r"^/(CF\d+)/(.+)$", re.IGNORECASE)


# ── BF16 / soft_prefix 生成 ──

def f32_to_bf16_u16(x: float) -> int:
    return (struct.unpack("<I", struct.pack("<f", x))[0] >> 16) & 0xFFFF


def make_sp_b64(val: float, p: int = SP_P, h: int = SP_H) -> str:
    raw = struct.pack("<H", f32_to_bf16_u16(val)) * (p * h)
    return base64.b64encode(raw).decode("ascii")


# ── AE×CF マトリクス ──

DEFAULT_MATRIX = {
    (0, 0): 1e-3,   (0, 1): 3e-3,   (0, 2): 7e-3,
    (1, 0): 3e-3,   (1, 1): 7e-3,   (1, 2): 1e-2,
    (2, 0): 7e-3,   (2, 1): 1e-2,   (2, 2): 1e-2,
}


class SensorMatrix:
    """AE(3段階) × CF(3段階) → soft_prefix値 のマトリクス"""

    def __init__(self, config: dict):
        mat_cfg = config.get("matrix", {})
        self.ae_thresholds = mat_cfg.get("ae_thresholds", [0.33, 0.66])
        self.cf_thresholds = mat_cfg.get("cf_thresholds", [-0.3, 0.3])
        v = mat_cfg.get("values", {})
        self.matrix = {
            (0, 0): v.get("low_worse",   DEFAULT_MATRIX[(0, 0)]),
            (0, 1): v.get("low_stable",  DEFAULT_MATRIX[(0, 1)]),
            (0, 2): v.get("low_better",  DEFAULT_MATRIX[(0, 2)]),
            (1, 0): v.get("mid_worse",   DEFAULT_MATRIX[(1, 0)]),
            (1, 1): v.get("mid_stable",  DEFAULT_MATRIX[(1, 1)]),
            (1, 2): v.get("mid_better",  DEFAULT_MATRIX[(1, 2)]),
            (2, 0): v.get("high_worse",  DEFAULT_MATRIX[(2, 0)]),
            (2, 1): v.get("high_stable", DEFAULT_MATRIX[(2, 1)]),
            (2, 2): v.get("high_better", DEFAULT_MATRIX[(2, 2)]),
        }

    def _ae_level(self, ae_norm: float) -> int:
        if ae_norm < self.ae_thresholds[0]: return 0
        elif ae_norm < self.ae_thresholds[1]: return 1
        return 2

    def _cf_level(self, pfi: float) -> int:
        if pfi < self.cf_thresholds[0]: return 0
        elif pfi < self.cf_thresholds[1]: return 1
        return 2

    def lookup(self, ae_norm: float, pfi: float) -> float:
        return self.matrix[(self._ae_level(ae_norm), self._cf_level(pfi))]

    def lookup_with_info(self, ae_norm: float, pfi: float) -> tuple[float, str]:
        ae_lv = self._ae_level(ae_norm)
        cf_lv = self._cf_level(pfi)
        val = self.matrix[(ae_lv, cf_lv)]
        ae_labels = ["低", "中", "高"]
        cf_labels = ["悪化", "安定", "良化"]
        return val, f"AE{ae_labels[ae_lv]}+CF{cf_labels[cf_lv]}"


# ── CFデバイス ──

class CFDeviceState:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.pfi_change: float = 0.0
        self.pfi_class: int = 3
        self.flag: str = "same"
        self.last_update: float = 0.0
        self.last_sent: float = 0.0
        self.ever_received: bool = False

    def update_pfi(self, value: float):
        self.pfi_change = value
        self.last_update = time.time()
        self.ever_received = True

    def update_class(self, value: int):
        self.pfi_class = value
        self.last_update = time.time()
        self.ever_received = True

    def update_flag(self, value: str):
        self.flag = value
        self.last_update = time.time()

    def is_updated(self) -> bool:
        return self.flag == "updated"

    def get_pfi(self) -> float:
        return self.pfi_change


# ── AEセンサー (ローカルCSV監視) ──

class AECsvWatcher:
    def __init__(self, config: dict):
        self.enabled = config.get("enabled", False)
        self.csv_dir = Path(config.get("csv_dir", "ae_csv"))
        if not self.csv_dir.is_absolute():
            self.csv_dir = Path(__file__).parent.parent / self.csv_dir
        self.poll_interval = config.get("poll_interval_sec", 30)
        self.ae_column = config.get("ae_column", "AE")
        self.max_ae_count = config.get("max_ae_count", 200.0)
        self.last_file: Optional[str] = None
        self.last_mtime: float = 0.0
        self.latest_ae: float = 0.0
        self.ae_normalized: float = 0.0

    def read_latest_csv(self) -> bool:
        if not self.csv_dir.exists():
            return False
        csv_files = sorted(self.csv_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime)
        if not csv_files:
            return False
        latest = csv_files[-1]
        mtime = latest.stat().st_mtime
        if str(latest) == self.last_file and mtime == self.last_mtime:
            return False
        try:
            with open(latest, encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            if not rows:
                return False
            ae_val = float(rows[-1][self.ae_column])
            date_str = rows[-1].get("Date", "")
            self.last_file = str(latest)
            self.last_mtime = mtime
            self.latest_ae = ae_val
            self.ae_normalized = max(0.0, min(1.0,
                ae_val / self.max_ae_count if self.max_ae_count > 0 else 0.0))
            logger.info(f"[AE] CSV更新: {latest.name} → "
                        f"AE={ae_val:.0f} norm={self.ae_normalized:.3f} (date={date_str})")
            return True
        except Exception as e:
            logger.error(f"[AE] CSV読み込み失敗: {latest} → {e}")
            return False

    async def poll_loop(self):
        if not self.enabled:
            logger.info("[AE] 無効 (ae_sensor.enabled = false)")
            return
        self.csv_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[AE] CSV監視開始: {self.csv_dir} (間隔: {self.poll_interval}s)")
        self.read_latest_csv()
        while True:
            self.read_latest_csv()
            await asyncio.sleep(self.poll_interval)


# ── RunPod 送信 (ubuntu_sender.py 統合) ──

class RunPodSender:
    """/mixer テキストをバッファリングし、JSON として RunPod へ SCP 送信"""

    def __init__(self, runpod_config: dict, dry_run: bool = False):
        self.enabled = bool(runpod_config)
        self.dry_run = dry_run
        self.cfg = runpod_config

        # バッファ設定
        sender_cfg = runpod_config.get("ubuntu_sender", {})
        self.min_chars = sender_cfg.get("min_chars_to_send", 50)
        self.max_wait_sec = sender_cfg.get("max_wait_sec", 30.0)
        self.max_items = sender_cfg.get("max_buffer_items", 20)

        self._buffer: list[dict] = []
        self._buffer_chars: int = 0
        self._buffer_first_time: float = 0.0
        self._lock = asyncio.Lock()

        # 統計
        self.stats = {"sent": 0, "failed": 0}

    def _ssh_base(self) -> list[str]:
        s = self.cfg["ssh"]
        key = os.path.expanduser(s["key"])
        cmd = ["ssh", "-i", key, "-p", str(s["port"])]
        cmd += s.get("options", [])
        if s.get("connect_timeout"):
            cmd += ["-o", f"ConnectTimeout={s['connect_timeout']}"]
        cmd.append(f"{s['user']}@{s['host']}")
        return cmd

    def _scp_base(self) -> list[str]:
        s = self.cfg["ssh"]
        key = os.path.expanduser(s["key"])
        cmd = ["scp", "-i", key, "-P", str(s["port"])]
        cmd += s.get("options", [])
        return cmd

    def _scp_target(self) -> str:
        s = self.cfg["ssh"]
        return f"{s['user']}@{s['host']}"

    async def ensure_remote_dir(self):
        if not self.enabled or self.dry_run:
            return
        remote_dir = self.cfg["runpod"]["osc_json_dir"]
        try:
            cmd = self._ssh_base() + [f"mkdir -p {remote_dir}"]
            await asyncio.to_thread(
                subprocess.run, cmd, check=True, capture_output=True, text=True, timeout=15
            )
            logger.info(f"[RunPod] リモートディレクトリ確認: {remote_dir}")
        except Exception as e:
            logger.warning(f"[RunPod] リモートディレクトリ作成失敗: {e}")

    async def add_text(self, text: str, address: str = "/mixer"):
        """テキストをバッファに追加し、閾値チェック"""
        if not self.enabled:
            return
        if not text:
            return

        now = datetime.now().astimezone()
        item = {
            "text": text,
            "received_at": now.isoformat(),
            "address": address,
        }

        async with self._lock:
            self._buffer.append(item)
            self._buffer_chars += len(text)
            if self._buffer_first_time == 0.0:
                self._buffer_first_time = time.time()
            current_chars = self._buffer_chars
            current_count = len(self._buffer)

        logger.debug(
            f"[RunPod] バッファ追加: {current_count}件/{current_chars}文字 "
            f"「{text[:50]}{'...' if len(text) > 50 else ''}」"
        )

        if current_chars >= self.min_chars:
            await self.flush(reason=f"{current_chars}文字 >= {self.min_chars}")
        elif current_count >= self.max_items:
            await self.flush(reason=f"{current_count}件 >= {self.max_items}")

    async def flush(self, reason: str = ""):
        """バッファをまとめて JSON として RunPod へ SCP"""
        async with self._lock:
            if not self._buffer:
                return
            items = self._buffer[:]
            total_chars = self._buffer_chars
            self._buffer = []
            self._buffer_chars = 0
            self._buffer_first_time = 0.0

        merged_text = "\n".join(item["text"] for item in items)
        now = datetime.now().astimezone()
        ts = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"mixer_{ts}.json"

        payload = {
            "received_at": now.isoformat(),
            "address": "/mixer",
            "text": merged_text,
            "item_count": len(items),
            "total_chars": total_chars,
            "items": items,
        }

        reason_str = f" ({reason})" if reason else ""
        logger.info(
            f"[RunPod] 📦 フラッシュ: {len(items)}件, {total_chars}文字{reason_str} "
            f"「{merged_text[:80]}{'...' if len(merged_text) > 80 else ''}」"
        )

        if self.dry_run:
            dry_dir = Path("./dry_run_json")
            dry_dir.mkdir(exist_ok=True)
            (dry_dir / filename).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            logger.info(f"[RunPod] (dry-run) 保存: {dry_dir / filename}")
            return

        ok = await asyncio.to_thread(self._upload_json, payload, filename)
        if ok:
            self.stats["sent"] += 1
            logger.info(f"[RunPod] ✅ 送信完了: {filename} (通算: {self.stats['sent']})")
        else:
            self.stats["failed"] += 1
            logger.error(f"[RunPod] ❌ 送信失敗 (通算失敗: {self.stats['failed']})")

    def _upload_json(self, payload: dict, filename: str) -> bool:
        remote_dir = self.cfg["runpod"]["osc_json_dir"]
        local_path = None
        try:
            with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
                f.write("\n")
                local_path = f.name

            remote_path = f"{remote_dir}/{filename}"
            target = f"{self._scp_target()}:{remote_path}"
            cmd = self._scp_base() + [local_path, target]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return True
        except Exception as e:
            logger.error(f"[RunPod] SCP失敗: {filename} → {e}")
            return False
        finally:
            if local_path:
                try:
                    os.unlink(local_path)
                except OSError:
                    pass

    async def timeout_watcher(self):
        """バッファのタイムアウト監視ループ"""
        if not self.enabled:
            return
        logger.info(
            f"[RunPod] タイムアウト監視開始: "
            f"{self.min_chars}文字 or {self.max_wait_sec}s or {self.max_items}件"
        )
        while True:
            await asyncio.sleep(1.0)
            async with self._lock:
                if not self._buffer or self._buffer_first_time == 0.0:
                    continue
                elapsed = time.time() - self._buffer_first_time
                count = len(self._buffer)
                chars = self._buffer_chars
            if elapsed >= self.max_wait_sec:
                await self.flush(
                    reason=f"タイムアウト {elapsed:.0f}s >= {self.max_wait_sec}s, "
                           f"{count}件/{chars}文字"
                )


# ── メインプロセッサ ──

class PlantSensorProcessor:

    def __init__(self, config: dict, runpod_config: dict = None,
                 dry_run: bool = False, no_runpod: bool = False):
        self.config = config
        self.cf_devices: dict[str, CFDeviceState] = {}
        self.dispatcher = Dispatcher()
        self.dry_run = dry_run

        self.sp_p = config.get("soft_prefix_p", SP_P)
        self.sp_h = config.get("soft_prefix_h", SP_H)

        # 送信先 Mac
        relay = config.get("relay_target", {"host": "10.0.0.202", "port": 8000})
        self.relay_host = relay["host"]
        self.relay_port = relay["port"]

        # マトリクス
        self.matrix = SensorMatrix(config)

        # CFデバイス
        for did, info in config.get("cf_devices", {}).items():
            if did.startswith("_"):
                continue
            self.cf_devices[did] = CFDeviceState(did)
        if not self.cf_devices:
            self.cf_devices["CF01"] = CFDeviceState("CF01")
            self.cf_devices["CF02"] = CFDeviceState("CF02")

        # AEセンサー
        self.ae_watcher = AECsvWatcher(config.get("ae_sensor", {}))

        # RunPod 送信
        if no_runpod or not runpod_config:
            self.runpod = RunPodSender({}, dry_run=dry_run)
        else:
            self.runpod = RunPodSender(runpod_config, dry_run=dry_run)

        # OSCハンドラ
        self.dispatcher.map("/mixer", self._on_mixer)
        self.dispatcher.set_default_handler(self._on_any)

        self._mixer_callback = None
        self.min_send_interval = config.get("min_send_interval_sec", 3.0)

    # ── OSCハンドラ ──

    def _ensure_cf_device(self, cf_id: str) -> CFDeviceState:
        if cf_id not in self.cf_devices:
            logger.info(f"✦ 新しいCFデバイス自動登録: {cf_id}")
            self.cf_devices[cf_id] = CFDeviceState(cf_id)
        return self.cf_devices[cf_id]

    def _on_any(self, address: str, *args):
        m = CF_PFI_PATTERN.match(address)
        if m:
            self._handle_pfi_combined(m.group(1), args)
            return
        m2 = CF_ANY_PATTERN.match(address)
        if m2:
            self._handle_cf_individual(m2.group(1), m2.group(2), args)
            return
        logger.debug(f"[unknown] {address}: {args}")

    def _handle_pfi_combined(self, cf_id: str, args: tuple):
        dev = self._ensure_cf_device(cf_id)
        try:
            if len(args) >= 9:
                pfi_change = float(args[6])
                pfi_class = int(args[7])
                flag = str(args[8])
            elif len(args) >= 3:
                pfi_change = float(args[-3])
                pfi_class = int(args[-2])
                flag = str(args[-1])
            else:
                logger.warning(f"[{cf_id}] /pfi unexpected args count={len(args)}: {args}")
                return

            old_flag = dev.flag
            dev.update_pfi(pfi_change)
            dev.update_class(pfi_class)
            dev.update_flag(flag)

            if flag == "updated" and old_flag != "updated":
                logger.info(
                    f"[{cf_id}] 🌱 データ更新! "
                    f"PFI={pfi_change:+.6f} class={pfi_class}"
                )
            else:
                logger.debug(
                    f"[{cf_id}] PFI={pfi_change:+.6f} "
                    f"class={pfi_class} flag={flag}"
                )
        except (ValueError, IndexError, TypeError) as e:
            logger.error(f"[{cf_id}] /pfi parse error: {e} args={args}")

    def _handle_cf_individual(self, cf_id: str, param: str, args: tuple):
        dev = self._ensure_cf_device(cf_id)
        if param == "PFI_degree_of_change" and args:
            dev.update_pfi(float(args[0]))
        elif param == "PFI_degree_of_change_class" and args:
            dev.update_class(int(args[0]))
        elif param == "flag" and args:
            old_flag = dev.flag
            dev.update_flag(str(args[0]))
            if args[0] == "updated" and old_flag != "updated":
                logger.info(f"[{cf_id}] 🌱 データ更新!")
        else:
            logger.debug(f"[{cf_id}] {param}: {args}")

    def _on_mixer(self, address: str, *args):
        text = " ".join(str(a) for a in args).strip()
        logger.info(f"[mixer] {text[:60]}")
        # RunPod送信バッファに追加 (非同期タスク)
        if self.runpod.enabled and text:
            asyncio.get_event_loop().call_soon_threadsafe(
                asyncio.ensure_future, self.runpod.add_text(text)
            )
        if self._mixer_callback:
            self._mixer_callback(address, *args)

    def set_mixer_callback(self, callback):
        self._mixer_callback = callback

    # ── Mac送信 ──

    def send_to_relay(self, text: str, sp_b64: str, source: str = "",
                      relay_count: int = 0):
        if self.dry_run:
            logger.info(f"(dry-run) [{source}] → {self.relay_host}:{self.relay_port} "
                        f"text={text} sp={sp_b64[:20]}...")
            return
        try:
            client = SimpleUDPClient(self.relay_host, self.relay_port)
            msg = osc_message_builder.OscMessageBuilder(address="/plantsensor")
            msg.add_arg(text)
            msg.add_arg(sp_b64)
            msg.add_arg(relay_count)
            client.send(msg.build())
            logger.info(
                f"[{source}] → {self.relay_host}:{self.relay_port} "
                f"/plantsensor text={text} "
                f"sp_b64={sp_b64[:40]}... relay={relay_count}"
            )
        except Exception as e:
            logger.error(f"送信失敗 {self.relay_host}:{self.relay_port}: {e}")

    # ── メインループ ──

    async def distribution_loop(self):
        logger.info("[配信] ループ開始")
        while True:
            ae_norm = self.ae_watcher.ae_normalized
            for device_id, dev in self.cf_devices.items():
                now = time.time()
                if (now - dev.last_sent) < self.min_send_interval:
                    continue
                pfi = dev.get_pfi()
                sp_val, label = self.matrix.lookup_with_info(ae_norm, pfi)
                sp_b64 = make_sp_b64(sp_val, self.sp_p, self.sp_h)
                received_marker = "" if dev.ever_received else " (未受信:default)"
                text = f"[{device_id}:PFI{pfi:+.02f},AE{ae_norm:.2f},{label}]"
                if dev.is_updated():
                    logger.info(
                        f"[{device_id}] 🌿 {label} → sp={sp_val} "
                        f"(PFI={pfi:+.3f}, AE_norm={ae_norm:.3f})"
                    )
                self.send_to_relay(text, sp_b64, source=f"{device_id}{received_marker}")
                dev.last_sent = now
            await asyncio.sleep(1.0)

    # ── 起動 ──

    async def start(self, listen_ip: str = "0.0.0.0", port: int = 8000):
        server = AsyncIOOSCUDPServer(
            (listen_ip, port), self.dispatcher, asyncio.get_event_loop()
        )
        transport, _ = await server.create_serve_endpoint()

        # RunPod 初期化
        if self.runpod.enabled:
            await self.runpod.ensure_remote_dir()

        logger.info("=" * 60)
        logger.info("🌱 植物センサー プロセッサ 起動")
        logger.info(f"  OSC受信:   {listen_ip}:{port}")
        logger.info(f"  送信先Mac: {self.relay_host}:{self.relay_port} /plantsensor")
        logger.info(f"  CFデバイス(初期): {list(self.cf_devices.keys())}")
        logger.info(f"  ※ 未登録のCFxx も自動追加されます")
        ae_status = f"有効 ({self.ae_watcher.csv_dir})" if self.ae_watcher.enabled else "無効"
        logger.info(f"  AEセンサー: {ae_status}")
        logger.info(f"  マトリクス:")
        for key in [(0,0),(0,1),(0,2),(1,0),(1,1),(1,2),(2,0),(2,1),(2,2)]:
            ae_l = ["AE低","AE中","AE高"][key[0]]
            cf_l = ["CF悪化","CF安定","CF良化"][key[1]]
            logger.info(f"    {ae_l}+{cf_l} → {self.matrix.matrix[key]}")
        logger.info(f"  配信間隔:  {self.min_send_interval}s")
        if self.runpod.enabled:
            ssh = self.runpod.cfg.get("ssh", {})
            logger.info(f"  RunPod送信: 有効 → {ssh.get('user')}@{ssh.get('host')}")
            logger.info(f"    リモート: {self.runpod.cfg.get('runpod', {}).get('osc_json_dir')}")
            logger.info(f"    バッファ: {self.runpod.min_chars}文字 or "
                        f"{self.runpod.max_wait_sec}s or {self.runpod.max_items}件")
        else:
            logger.info(f"  RunPod送信: 無効")
        if self.dry_run:
            logger.info("  モード:    dry-run (送信なし)")
        logger.info("=" * 60)

        tasks = [
            asyncio.create_task(self.distribution_loop()),
            asyncio.create_task(self.ae_watcher.poll_loop()),
            asyncio.create_task(self.runpod.timeout_watcher()),
        ]
        await asyncio.gather(*tasks)


# ── 設定読み込み ──

def load_config(config_path: Optional[str] = None) -> dict:
    candidates = []
    if config_path:
        candidates.append(Path(config_path))
    candidates.append(Path(__file__).parent / "plant_sensor_config.json")
    candidates.append(Path(__file__).parent.parent / "config" / "plant_sensor_config.json")
    for p in candidates:
        if p.exists():
            logger.info(f"config読み込み: {p}")
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    logger.info("configなし、デフォルト設定を使用")
    return {}


def load_runpod_config() -> dict:
    """runpod_config.json を探して読み込む"""
    candidates = [
        Path(__file__).parent / "runpod_config.json",
        Path(__file__).parent.parent / "runpod" / "runpod_config.json",
        Path(__file__).parent.parent / "config" / "runpod_config.json",
    ]
    for p in candidates:
        if p.exists():
            logger.info(f"RunPod config読み込み: {p}")
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    logger.info("RunPod configなし、RunPod送信を無効化")
    return {}


def main():
    parser = argparse.ArgumentParser(description="植物センサー → soft_prefix → Mac + RunPod")
    parser.add_argument("--config", default=None, help="植物センサー設定JSONファイル")
    parser.add_argument("--runpod-config", default=None, help="RunPod設定JSONファイル")
    parser.add_argument("--port", type=int, default=None, help="OSC受信ポート")
    parser.add_argument("--dry-run", action="store_true", help="送信なし")
    parser.add_argument("--no-runpod", action="store_true", help="RunPod送信を無効化")
    args = parser.parse_args()

    config = load_config(args.config)
    listen_ip = config.get("listen_ip", "0.0.0.0")
    port = args.port or config.get("listen_port", 8000)

    if args.no_runpod:
        runpod_config = {}
    elif args.runpod_config:
        with open(args.runpod_config, encoding="utf-8") as f:
            runpod_config = json.load(f)
    else:
        runpod_config = load_runpod_config()

    processor = PlantSensorProcessor(
        config, runpod_config=runpod_config,
        dry_run=args.dry_run, no_runpod=args.no_runpod
    )
    asyncio.run(processor.start(listen_ip, port))


if __name__ == "__main__":
    main()
