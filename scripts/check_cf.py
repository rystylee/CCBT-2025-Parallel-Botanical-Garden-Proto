#!/usr/bin/env python3
"""
CF (クロロフィル蛍光) デバイス受信チェック — スタンドアロン版

10.0.0.200 上で実行し、CF デバイスからの OSC メッセージを
受信できているか確認する。プロジェクト内モジュールへの依存なし。

/CF1, /CF2, /CF00, /CF01 等すべての /CF* プレフィックスをキャッチ。

使い方:
  # デフォルト (port 8000, 60秒)
  uv run python scripts/check_cf.py

  # ポート・時間指定
  uv run python scripts/check_cf.py --port 8000 --duration 120

  # 詳細ログ (全受信メッセージ表示)
  uv run python scripts/check_cf.py --verbose
"""
import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from typing import Dict

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer


CLASS_LABELS = {
    0: "getting_much_worse",
    1: "getting_worse",
    2: "getting_slightly_worse",
    3: "no_change",
    4: "getting_slightly_better",
    5: "getting_better",
    6: "getting_much_better",
}


@dataclass
class CFState:
    pfi_change: float = 0.0
    pfi_class: int = 3
    flag: str = "same"
    timestamp: float = 0.0
    update_count: int = 0
    msg_count: int = 0


class CFChecker:
    """全 /CF* OSC メッセージを受信・表示"""

    def __init__(self, port: int, verbose: bool):
        self.port = port
        self.verbose = verbose
        self.devices: Dict[str, CFState] = {}
        self._dispatcher = Dispatcher()
        self._dispatcher.set_default_handler(self._on_any)

    def _get_device(self, address: str):
        """'/CF1/PFI_degree_of_change' → ('CF1', 'PFI_degree_of_change')"""
        parts = address.strip("/").split("/", 1)
        if len(parts) < 2:
            return None, None
        cf_id = parts[0]
        param = parts[1]
        if cf_id not in self.devices:
            self.devices[cf_id] = CFState()
            print(f"  ✦ 新しいデバイス検出: {cf_id}")
        return cf_id, param

    def _on_any(self, address: str, *args):
        if not address.startswith("/CF"):
            if self.verbose:
                print(f"  (other) {address}: {args}")
            return

        cf_id, param = self._get_device(address)
        if cf_id is None:
            return

        dev = self.devices[cf_id]
        dev.msg_count += 1
        dev.timestamp = time.time()

        if param == "PFI_degree_of_change" and args:
            dev.pfi_change = float(args[0])
            if self.verbose:
                print(f"  [{cf_id}] PFI change = {dev.pfi_change:+.4f}")

        elif param == "PFI_degree_of_change_class" and args:
            dev.pfi_class = int(args[0])
            if self.verbose:
                label = CLASS_LABELS.get(dev.pfi_class, "?")
                print(f"  [{cf_id}] PFI class  = {dev.pfi_class} ({label})")

        elif param == "flag" and args:
            val = str(args[0])
            dev.flag = val
            if val == "updated":
                dev.update_count += 1
                print(f"  [{cf_id}] ★ DATA UPDATED (count={dev.update_count})")
            elif self.verbose:
                print(f"  [{cf_id}] flag = {val}")
        else:
            if self.verbose:
                print(f"  [{cf_id}] {param} = {args}")

    async def start(self):
        server = AsyncIOOSCUDPServer(
            ("0.0.0.0", self.port), self._dispatcher, asyncio.get_event_loop()
        )
        transport, _ = await server.create_serve_endpoint()
        return transport


async def run_check(port: int, duration: float, verbose: bool):
    checker = CFChecker(port, verbose)
    transport = await checker.start()

    print()
    print("=" * 60)
    print(f"  CF 受信チェック — port {port}")
    print(f"  CF1 (10.0.0.211), CF2 (10.0.0.212) → ここ")
    print(f"  全 /CF* プレフィックスをキャッチ")
    print(f"  {duration:.0f}秒間モニタリング... (Ctrl+C で終了)")
    print("=" * 60)
    print()

    start = time.time()
    last_print = 0

    try:
        while (time.time() - start) < duration:
            await asyncio.sleep(1.0)
            elapsed = int(time.time() - start)

            # 3秒ごとにステータス表示
            if elapsed - last_print >= 3:
                last_print = elapsed

                if not checker.devices:
                    print(f"[{elapsed:4d}s] 受信待ち...")
                    continue

                print(f"[{elapsed:4d}s] ──────────────────────────────────")
                for cf_id in sorted(checker.devices.keys()):
                    dev = checker.devices[cf_id]
                    age = time.time() - dev.timestamp if dev.timestamp > 0 else 999
                    alive = age < 5.0
                    status = "● ALIVE" if alive else f"○ {age:.0f}s ago"
                    cls_label = CLASS_LABELS.get(dev.pfi_class, "?")
                    print(
                        f"  {cf_id}: {status}  "
                        f"change={dev.pfi_change:+.4f}  "
                        f"class={dev.pfi_class} ({cls_label})  "
                        f"flag={dev.flag}  "
                        f"updates={dev.update_count}  "
                        f"msgs={dev.msg_count}"
                    )
                print()

    except asyncio.CancelledError:
        pass

    transport.close()

    # サマリー
    print()
    print("=" * 60)
    print("  結果サマリー")
    print("=" * 60)

    if not checker.devices:
        print("  ! デバイスから受信なし。確認事項:")
        print(f"    - CFデバイスの送信先が 10.0.0.200:{port} になっているか")
        print(f"    - ファイアウォールで UDP {port} が開いているか")
        print(f"    - CFデバイスが起動して計測中か")
        print()
        print("  ローカルテスト:")
        print("    別ターミナルで simulate_cf.py を実行:")
        print(f"    uv run python scripts/simulate_cf.py --port {port}")
        print()
        return 1

    for cf_id in sorted(checker.devices.keys()):
        dev = checker.devices[cf_id]
        print(
            f"  {cf_id}: OK — msgs={dev.msg_count}, "
            f"updates={dev.update_count}, "
            f"最終 change={dev.pfi_change:+.4f}, class={dev.pfi_class}"
        )
    print()
    return 0


def main():
    parser = argparse.ArgumentParser(description="CF device OSC reception check")
    parser.add_argument("--port", type=int, default=8000,
                        help="OSC listen port (default: 8000)")
    parser.add_argument("--duration", type=float, default=60,
                        help="Monitor duration in seconds (default: 60)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every received message")
    args = parser.parse_args()

    try:
        rc = asyncio.run(run_check(args.port, args.duration, args.verbose))
    except KeyboardInterrupt:
        print("\n中断しました")
        rc = 0

    sys.exit(rc)


if __name__ == "__main__":
    main()
