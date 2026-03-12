#!/usr/bin/env python3
"""植物センサー → soft_prefix → Mac(10.0.0.202) 配信

AE×CF 2軸マトリクスで soft_prefix の「揺らぎの性格」を決定する。
全状態がLLMに強い影響を与える設計。植物が静かでも活発でも、
生成される詩のトーンが植物の状態に連動して変化する。

=== マトリクス ===
               CF悪化(<-0.3)  CF安定(-0.3~0.3)  CF良化(>0.3)
  AE低(<0.33)    1e-3(収束的)    3e-3              7e-3
  AE中(0.33~0.66) 3e-3           7e-3              1e-2
  AE高(>0.66)    7e-3            1e-2              1e-2(発散的)

使い方:
    python3 plant_sensor_processor.py
    python3 plant_sensor_processor.py --config path/to/plant_sensor_config.json
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

import base64
import struct

SP_P = 1
SP_H = 1536


# ── BF16 / soft_prefix 生成 ──

def f32_to_bf16_u16(x: float) -> int:
    return (struct.unpack("<I", struct.pack("<f", x))[0] >> 16) & 0xFFFF


def make_sp_b64(val: float, p: int = SP_P, h: int = SP_H) -> str:
    raw = struct.pack("<H", f32_to_bf16_u16(val)) * (p * h)
    return base64.b64encode(raw).decode("ascii")


# ── AE×CF マトリクス ──

# デフォルト値 (configで上書き可能)
DEFAULT_MATRIX = {
    # [AE段階][CF段階]
    # AE低
    (0, 0): 1e-3,   # low_worse:  沈黙+衰退 → 収束的・反復的
    (0, 1): 3e-3,   # low_stable: 沈黙+安定 → やや柔らかい
    (0, 2): 7e-3,   # low_better: 静かだが回復中 → 静寂からの跳躍
    # AE中
    (1, 0): 3e-3,   # mid_worse:  活動中だが効率低下
    (1, 1): 7e-3,   # mid_stable: 通常の活動
    (1, 2): 1e-2,   # mid_better: 活動中+改善 → 自由な展開
    # AE高
    (2, 0): 7e-3,   # high_worse: ストレス下で必死 → 緊張感
    (2, 1): 1e-2,   # high_stable: 全力活動
    (2, 2): 1e-2,   # high_better: 最も活発 → 最大の発散
}


class SensorMatrix:
    """AE(3段階) × CF(3段階) → soft_prefix値 のマトリクス"""

    def __init__(self, config: dict):
        mat_cfg = config.get("matrix", {})

        self.ae_thresholds = mat_cfg.get("ae_thresholds", [0.33, 0.66])
        self.cf_thresholds = mat_cfg.get("cf_thresholds", [-0.3, 0.3])

        # config の values からマトリクス構築
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
        """AE正規化値 → 0(低), 1(中), 2(高)"""
        if ae_norm < self.ae_thresholds[0]:
            return 0
        elif ae_norm < self.ae_thresholds[1]:
            return 1
        return 2

    def _cf_level(self, pfi: float) -> int:
        """PFI値 → 0(悪化), 1(安定), 2(良化)"""
        if pfi < self.cf_thresholds[0]:
            return 0
        elif pfi < self.cf_thresholds[1]:
            return 1
        return 2

    def lookup(self, ae_norm: float, pfi: float) -> float:
        """AE正規化値 + PFI → soft_prefix BF16値"""
        ae_lv = self._ae_level(ae_norm)
        cf_lv = self._cf_level(pfi)
        val = self.matrix[(ae_lv, cf_lv)]
        return val

    def lookup_with_info(self, ae_norm: float, pfi: float) -> tuple[float, str]:
        """lookup + デバッグ用ラベル"""
        ae_lv = self._ae_level(ae_norm)
        cf_lv = self._cf_level(pfi)
        val = self.matrix[(ae_lv, cf_lv)]
        ae_labels = ["低", "中", "高"]
        cf_labels = ["悪化", "安定", "良化"]
        label = f"AE{ae_labels[ae_lv]}+CF{cf_labels[cf_lv]}"
        return val, label


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

    def get_pfi(self) -> Optional[float]:
        """PFI float を優先、なければ class から復元"""
        if self.pfi_change is not None:
            return self.pfi_change
        if self.pfi_class is not None:
            # class(0~6) → float(-1~1) に近似変換
            return (self.pfi_class - 3) / 3.0
        return None


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
        """最新CSVを読み、値が更新されたら True"""
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

            # 最終行の AE 値
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
        """定期的にCSVフォルダを監視"""
        if not self.enabled:
            logger.info("[AE] 無効 (ae_sensor.enabled = false)")
            return

        self.csv_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[AE] CSV監視開始: {self.csv_dir} (間隔: {self.poll_interval}s)")

        # 初回読み込み
        self.read_latest_csv()

        while True:
            self.read_latest_csv()
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

        # マトリクス
        self.matrix = SensorMatrix(config)

        # CFデバイス
        for did, info in config.get("cf_devices", {}).items():
            if did.startswith("_"):
                continue
            self.cf_devices[did] = CFDeviceState(did)
        if not self.cf_devices:
            self.cf_devices["CF00"] = CFDeviceState("CF00")
            self.cf_devices["CF01"] = CFDeviceState("CF01")

        # AEセンサー
        self.ae_watcher = AECsvWatcher(config.get("ae_sensor", {}))

        # OSCハンドラ
        for did in self.cf_devices:
            # 個別アドレス (仕様書パターン)
            self.dispatcher.map(f"/{did}/PFI_degree_of_change", self._on_pfi, did)
            self.dispatcher.map(f"/{did}/PFI_degree_of_change_class", self._on_pfi_class, did)
            self.dispatcher.map(f"/{did}/flag", self._on_flag, did)
            # まとめ送信パターン (実機の実際の送信形式)
            self.dispatcher.map(f"/{did}/pfi", self._on_pfi_combined, did)

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
                logger.info(f"[{device_id}] 🌱 データ更新!")

    def _on_pfi_combined(self, address: str, *args):
        """まとめ送信パターン: /{CFxx}/pfi timestamp Fo Fm ? ? ? PFI_change class flag

        実機から送信される形式:
          args = (timestamp, Fo, Fm, val3, val4, val5, PFI_degree_of_change, class, flag, device_id)
          最後の device_id は dispatcher.map の追加引数
        """
        device_id = args[-1]   # dispatcher.map の追加引数
        raw_args = args[:-1]   # 最後の device_id を除く実データ
        dev = self.cf_devices.get(device_id)
        if not dev:
            return

        try:
            # args: (timestamp, Fo, Fm, ?, ?, ?, PFI_change, class, flag)
            if len(raw_args) >= 9:
                pfi_change = float(raw_args[6])
                pfi_class = int(raw_args[7])
                flag = str(raw_args[8])
            elif len(raw_args) >= 7:
                # フォールバック: 短い場合
                pfi_change = float(raw_args[-3])
                pfi_class = int(raw_args[-2])
                flag = str(raw_args[-1])
            else:
                logger.warning(f"[{device_id}] /pfi unexpected args count={len(raw_args)}: {raw_args}")
                return

            old_flag = dev.flag
            dev.update_pfi(pfi_change)
            dev.update_class(pfi_class)
            dev.update_flag(flag)

            if flag == "updated" and old_flag != "updated":
                logger.info(
                    f"[{device_id}] 🌱 データ更新! "
                    f"PFI={pfi_change:+.6f} class={pfi_class} "
                    f"(Fo={raw_args[1]}, Fm={raw_args[2]})"
                )
            else:
                logger.info(
                    f"[{device_id}] /pfi PFI={pfi_change:+.6f} "
                    f"class={pfi_class} flag={flag}"
                )

        except (ValueError, IndexError) as e:
            logger.error(f"[{device_id}] /pfi parse error: {e} args={raw_args}")

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

    # ── メインループ: CF受信トリガーでAE参照 → マトリクス → 送信 ──

    async def distribution_loop(self):
        """CFデバイスのデータ受信をトリガーに、AEを参照して
        マトリクスからsoft_prefixを生成し、CFデバイスごとに送信"""
        logger.info("[配信] ループ開始")

        while True:
            ae_norm = self.ae_watcher.ae_normalized

            for device_id, dev in self.cf_devices.items():
                now = time.time()

                if (now - dev.last_sent) < self.min_send_interval:
                    continue

                pfi = dev.get_pfi()
                if pfi is None:
                    logger.info(f"[{device_id}] pfi=None, skipping (pfi_change={dev.pfi_change}, pfi_class={dev.pfi_class})")
                    continue

                # マトリクス参照
                sp_val, label = self.matrix.lookup_with_info(ae_norm, pfi)
                sp_b64 = make_sp_b64(sp_val, self.sp_p, self.sp_h)

                text = f"[{device_id}:PFI{pfi:+.2f},AE{ae_norm:.2f},{label}]"

                if dev.is_updated():
                    logger.info(
                        f"[{device_id}] 🌿 {label} → sp={sp_val} "
                        f"(PFI={pfi:+.3f}, AE_norm={ae_norm:.3f})"
                    )

                self.send_to_relay(text, sp_b64, source=device_id)
                dev.last_sent = now

            await asyncio.sleep(1.0)

    # ── 起動 ──

    async def start(self, listen_ip: str = "0.0.0.0", port: int = 8000):
        server = AsyncIOOSCUDPServer(
            (listen_ip, port), self.dispatcher, asyncio.get_event_loop()
        )
        transport, _ = await server.create_serve_endpoint()

        logger.info("=" * 60)
        logger.info("🌱 植物センサー プロセッサ 起動")
        logger.info(f"  OSC受信:   {listen_ip}:{port}")
        logger.info(f"  送信先Mac: {self.relay_host}:{self.relay_port}")
        logger.info(f"  CFデバイス: {list(self.cf_devices.keys())}")
        ae_status = f"有効 ({self.ae_watcher.csv_dir})" if self.ae_watcher.enabled else "無効"
        logger.info(f"  AEセンサー: {ae_status}")
        logger.info(f"  マトリクス:")
        for key in [(0,0),(0,1),(0,2),(1,0),(1,1),(1,2),(2,0),(2,1),(2,2)]:
            ae_l = ["AE低","AE中","AE高"][key[0]]
            cf_l = ["CF悪化","CF安定","CF良化"][key[1]]
            logger.info(f"    {ae_l}+{cf_l} → {self.matrix.matrix[key]}")
        logger.info(f"  配信間隔:  {self.min_send_interval}s")
        if self.dry_run:
            logger.info("  モード:    dry-run (送信なし)")
        logger.info("=" * 60)

        tasks = [
            asyncio.create_task(self.distribution_loop()),
            asyncio.create_task(self.ae_watcher.poll_loop()),
        ]
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
