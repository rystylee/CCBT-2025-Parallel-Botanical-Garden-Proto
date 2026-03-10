#!/usr/bin/env python3
"""植物センサー → soft_prefix → Mac(10.0.0.202) 配信

Ubuntu (10.0.0.200) 上で動作。
CFデバイス(OSC) / AEセンサー(ローカルCSV) のデータを受信・取得し、
soft_prefix に変換して Mac (10.0.0.202) へ OSC 送信する。

=== CFデバイス (クロロフィル蛍光計測) ===
  IP: 10.0.0.211 (CF01), 10.0.0.212 (CF02)
  プロトコル: OSC → Ubuntu:8000
  /CF0x/PFI_degree_of_change       float (-1.0 ~ 1.0)
  /CF0x/PFI_degree_of_change_class int (0~6, 3=no change)
  /CF0x/flag                       "same" | "updated"

=== AEセンサー (陰山先生) ===
  CSV手動DL → ae_csv/ フォルダへ配置
  CSV形式: "Time (hr)","Date","AE","AE1ch","AE2ch"
  最新CSVの最終行のAE値を使用

使い方:
    python3 plant_sensor_processor.py
    python3 plant_sensor_processor.py --config plant_sensor_config.json
    python3 plant_sensor_processor.py --dry-run
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from loguru import logger
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient
from pythonosc import osc_message_builder

# ── soft_prefix 生成 (bi/utils.py 互換) ──
import base64
import struct

SP_P = 1
SP_H = 1536


def f32_to_bf16_u16(x: float) -> int:
    return (struct.unpack("<I", struct.pack("<f", x))[0] >> 16) & 0xFFFF


def make_sp_b64(val: float, p: int = SP_P, h: int = SP_H) -> str:
    raw = struct.pack("<H", f32_to_bf16_u16(val)) * (p * h)
    return base64.b64encode(raw).decode("ascii")


def pfi_to_sp_b64(pfi: float, p: int = SP_P, h: int = SP_H) -> str:
    """PFI変化度合い (-1.0~1.0) → soft_prefix base64"""
    pfi = max(-1.0, min(1.0, pfi))
    if pfi < -0.5:
        val = 0.0
    elif pfi < 0.0:
        val = 1e-4
    elif pfi < 0.5:
        val = 1e-3
    else:
        val = 1e-2
    return make_sp_b64(val, p, h)


def pfi_class_to_sp_b64(cls: int, p: int = SP_P, h: int = SP_H) -> str:
    """PFIクラス (0~6) → soft_prefix base64"""
    cls = max(0, min(6, cls))
    if cls <= 1:
        val = 0.0
    elif cls <= 2:
        val = 1e-4
    elif cls <= 4:
        val = 1e-3
    else:
        val = 1e-2
    return make_sp_b64(val, p, h)


def ae_to_sp_b64(ae_count: float, max_count: float = 200.0,
                 p: int = SP_P, h: int = SP_H) -> str:
    """AEカウント値 → 正規化 → soft_prefix base64

    AE値 / max_count で 0~1 に変換してからマッピング:
      0.00 ~ 0.25  → 0.0   (ほぼ無音)
      0.25 ~ 0.50  → 1e-4  (低活性)
      0.50 ~ 0.75  → 1e-3  (中活性)
      0.75 ~ 1.00  → 1e-2  (高活性)
    """
    normalized = max(0.0, min(1.0, ae_count / max_count)) if max_count > 0 else 0.0
    if normalized < 0.25:
        val = 0.0
    elif normalized < 0.50:
        val = 1e-4
    elif normalized < 0.75:
        val = 1e-3
    else:
        val = 1e-2
    return make_sp_b64(val, p, h)


# ── CFデバイス ──

class CFDeviceState:
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.pfi_change: Optional[float] = None
        self.pfi_class: Optional[int] = None
        self.flag: str = "same"
        self.last_update: float = 0.0
        self.last_sent: float = 0.0

    def update_pfi(self, value: float):
        self.pfi_change = value
        self.last_update = time.time()

    def update_class(self, value: int):
        self.pfi_class = value
        self.last_update = time.time()

    def update_flag(self, value: str):
        self.flag = value
        self.last_update = time.time()

    def is_updated(self) -> bool:
        return self.flag == "updated"

    def get_sp_b64(self, p: int = SP_P, h: int = SP_H) -> Optional[str]:
        if self.pfi_change is not None:
            return pfi_to_sp_b64(self.pfi_change, p, h)
        if self.pfi_class is not None:
            return pfi_class_to_sp_b64(self.pfi_class, p, h)
        return None

    def get_text(self) -> str:
        parts = []
        if self.pfi_change is not None:
            parts.append(f"PFI:{self.pfi_change:+.3f}")
        if self.pfi_class is not None:
            labels = ["much_worse", "worse", "slightly_worse", "stable",
                      "slightly_better", "better", "much_better"]
            label = labels[max(0, min(6, self.pfi_class))]
            parts.append(label)
        return f"[{self.device_id}:{','.join(parts)}]" if parts else f"[{self.device_id}]"


# ── AEセンサー (ローカルCSV監視) ──

class AECsvWatcher:
    """ae_csv/ フォルダを監視し、最新CSVの最終行のAE値を読み取る"""

    def __init__(self, config: dict):
        self.enabled = config.get("enabled", False)
        self.csv_dir = Path(config.get("csv_dir", "ae_csv"))
        # 相対パスならプロジェクトルート (input_controller/ の親) 基準に解決
        if not self.csv_dir.is_absolute():
            project_root = Path(__file__).parent.parent
            self.csv_dir = project_root / self.csv_dir
        self.poll_interval = config.get("poll_interval_sec", 30)
        self.ae_column = config.get("ae_column", "AE")
        self.max_ae_count = config.get("max_ae_count", 200.0)
        self.last_file: Optional[str] = None
        self.last_mtime: float = 0.0
        self.latest_ae: Optional[float] = None
        self.latest_date: str = ""

    def read_latest_csv(self) -> Optional[dict]:
        """最新のCSVファイルを見つけて最終行を返す"""
        if not self.csv_dir.exists():
            return None

        csv_files = sorted(self.csv_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime)
        if not csv_files:
            return None

        latest = csv_files[-1]
        mtime = latest.stat().st_mtime

        # ファイルが変わっていなければスキップ
        if str(latest) == self.last_file and mtime == self.last_mtime:
            return None

        try:
            with open(latest, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            if not rows:
                return None

            # 最終行からAE値取得
            last_row = rows[-1]
            ae_val = float(last_row[self.ae_column])
            date_str = last_row.get("Date", "")

            self.last_file = str(latest)
            self.last_mtime = mtime
            self.latest_ae = ae_val
            self.latest_date = date_str

            logger.info(f"[AE] CSV読み込み: {latest.name} → "
                        f"AE={ae_val:.0f} (date={date_str})")

            return {"ae": ae_val, "date": date_str, "file": latest.name}

        except Exception as e:
            logger.error(f"[AE] CSV読み込み失敗: {latest} → {e}")
            return None

    async def poll_loop(self, sp_p: int, sp_h: int, max_count: float, send_fn):
        """定期的にCSVフォルダを監視"""
        if not self.enabled:
            logger.info("[AE] 無効 (ae_sensor.enabled = false)")
            return

        self.csv_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[AE] CSV監視開始: {self.csv_dir} (間隔: {self.poll_interval}s)")

        while True:
            result = self.read_latest_csv()
            if result:
                ae_val = result["ae"]
                sp_b64 = ae_to_sp_b64(ae_val, max_count, sp_p, sp_h)
                normalized = min(1.0, ae_val / max_count) if max_count > 0 else 0.0
                text = f"[AE:{ae_val:.0f},norm:{normalized:.2f}]"
                send_fn(text, sp_b64, source="AE")

            await asyncio.sleep(self.poll_interval)


# ── メインプロセッサ ──

class PlantSensorProcessor:

    def __init__(self, config: dict):
        self.config = config
        self.cf_devices: dict[str, CFDeviceState] = {}
        self.dispatcher = Dispatcher()
        self.dry_run = False

        self.sp_p = config.get("soft_prefix_p", SP_P)
        self.sp_h = config.get("soft_prefix_h", SP_H)

        # 送信先 Mac
        relay = config.get("relay_target", {"host": "10.0.0.202", "port": 8000})
        self.relay_host = relay["host"]
        self.relay_port = relay["port"]

        # CFデバイス
        for did, info in config.get("cf_devices", {}).items():
            if did.startswith("_"):
                continue
            self.cf_devices[did] = CFDeviceState(did)
        if not self.cf_devices:
            self.cf_devices["CF01"] = CFDeviceState("CF01")
            self.cf_devices["CF02"] = CFDeviceState("CF02")

        # AEセンサー
        ae_cfg = config.get("ae_sensor", {})
        self.ae_watcher = AECsvWatcher(ae_cfg)
        self.ae_max_count = ae_cfg.get("max_ae_count", 200.0)

        # OSCハンドラ
        self.dispatcher.map("/CF01/PFI_degree_of_change", self._on_pfi, "CF01")
        self.dispatcher.map("/CF02/PFI_degree_of_change", self._on_pfi, "CF02")
        self.dispatcher.map("/CF01/PFI_degree_of_change_class", self._on_pfi_class, "CF01")
        self.dispatcher.map("/CF02/PFI_degree_of_change_class", self._on_pfi_class, "CF02")
        self.dispatcher.map("/CF01/flag", self._on_flag, "CF01")
        self.dispatcher.map("/CF02/flag", self._on_flag, "CF02")
        self.dispatcher.map("/mixer", self._on_mixer)
        self.dispatcher.set_default_handler(self._on_unknown)

        self._mixer_callback = None
        self.min_send_interval = config.get("min_send_interval_sec", 3.0)

    # ── OSCハンドラ ──

    def _on_pfi(self, address: str, *args):
        device_id = args[-1]
        value = float(args[0])
        dev = self.cf_devices.get(device_id)
        if dev:
            dev.update_pfi(value)
            logger.debug(f"[{device_id}] PFI: {value:+.4f}")

    def _on_pfi_class(self, address: str, *args):
        device_id = args[-1]
        value = int(args[0])
        dev = self.cf_devices.get(device_id)
        if dev:
            dev.update_class(value)
            logger.debug(f"[{device_id}] Class: {value}")

    def _on_flag(self, address: str, *args):
        device_id = args[-1]
        value = str(args[0])
        dev = self.cf_devices.get(device_id)
        if dev:
            old_flag = dev.flag
            dev.update_flag(value)
            if value == "updated" and old_flag != "updated":
                logger.info(f"[{device_id}] 🌱 データ更新! PFI={dev.pfi_change}")

    def _on_mixer(self, address: str, *args):
        text = " ".join(str(a) for a in args).strip()
        logger.info(f"[mixer] {text[:60]}")
        if self._mixer_callback:
            self._mixer_callback(address, *args)

    def _on_unknown(self, address: str, *args):
        logger.debug(f"[unknown] {address}: {args}")

    def set_mixer_callback(self, callback):
        self._mixer_callback = callback

    # ── Mac送信 ──

    def send_to_relay(self, text: str, sp_b64: str, source: str = "",
                      relay_count: int = 0):
        if self.dry_run:
            logger.info(f"(dry-run) [{source}] text={text} sp={sp_b64[:20]}...")
            return

        try:
            client = SimpleUDPClient(self.relay_host, self.relay_port)
            msg = osc_message_builder.OscMessageBuilder(address="/bi/input")
            msg.add_arg(text)
            msg.add_arg(sp_b64)
            msg.add_arg(relay_count)
            client.send(msg.build())
            logger.debug(f"[{source}] → {self.relay_host}:{self.relay_port}")
        except Exception as e:
            logger.error(f"送信失敗 {self.relay_host}:{self.relay_port}: {e}")

    # ── CF配信ループ ──

    async def cf_distribution_loop(self):
        logger.info("[CF] 配信ループ開始")
        while True:
            for device_id, dev in self.cf_devices.items():
                now = time.time()
                if (now - dev.last_sent) < self.min_send_interval:
                    continue

                sp_b64 = dev.get_sp_b64(self.sp_p, self.sp_h)
                if sp_b64 is None:
                    continue

                text = dev.get_text()
                if dev.is_updated():
                    logger.info(f"[{device_id}] 🌿 配信: {text}")
                self.send_to_relay(text, sp_b64, source=device_id)
                dev.last_sent = now

            await asyncio.sleep(1.0)

    # ── 起動 ──

    async def start(self, listen_ip: str = "0.0.0.0", port: int = 8000):
        server = AsyncIOOSCUDPServer(
            (listen_ip, port), self.dispatcher, asyncio.get_event_loop()
        )
        transport, _ = await server.create_serve_endpoint()

        logger.info("=" * 55)
        logger.info("🌱 植物センサー プロセッサ 起動")
        logger.info(f"  OSC受信:   {listen_ip}:{port}")
        logger.info(f"  送信先Mac: {self.relay_host}:{self.relay_port}")
        logger.info(f"  CFデバイス: {list(self.cf_devices.keys())}")
        ae_status = f"有効 ({self.ae_watcher.csv_dir})" if self.ae_watcher.enabled else "無効"
        logger.info(f"  AEセンサー: {ae_status}")
        logger.info(f"  配信間隔:  {self.min_send_interval}s")
        if self.dry_run:
            logger.info("  モード:    dry-run (送信なし)")
        logger.info("=" * 55)

        tasks = [asyncio.create_task(self.cf_distribution_loop())]

        if self.ae_watcher.enabled:
            tasks.append(asyncio.create_task(
                self.ae_watcher.poll_loop(
                    self.sp_p, self.sp_h, self.ae_max_count, self.send_to_relay)
            ))

        await asyncio.gather(*tasks)


# ── 設定 ──

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


def main():
    parser = argparse.ArgumentParser(description="植物センサー → soft_prefix → Mac")
    parser.add_argument("--config", default=None, help="設定JSONファイル")
    parser.add_argument("--port", type=int, default=None, help="OSC受信ポート")
    parser.add_argument("--dry-run", action="store_true", help="送信なし")
    args = parser.parse_args()

    config = load_config(args.config)
    listen_ip = config.get("listen_ip", "0.0.0.0")
    port = args.port or config.get("listen_port", 8000)

    processor = PlantSensorProcessor(config)
    processor.dry_run = args.dry_run
    asyncio.run(processor.start(listen_ip, port))


if __name__ == "__main__":
    main()
