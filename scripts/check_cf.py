#!/usr/bin/env python3
"""
CF (クロロフィル蛍光) デバイス受信チェック — スタンドアロン版

10.0.0.200 上で実行し、CF デバイスからの OSC メッセージを
受信できているか確認する。プロジェクト内モジュールへの依存なし。

全 /CF* プレフィックスをキャッチ。

使い方:
  # デフォルト (port 8000, 60秒)
  uv run python scripts/check_cf.py

  # 全メッセージをそのまま表示 (推奨: まず --raw で確認)
  uv run python scripts/check_cf.py --raw

  # ポート全受信 (CF以外も含む全OSCを表示)
  uv run python scripts/check_cf.py --raw --all

  # ポート・時間指定
  uv run python scripts/check_cf.py --port 8000 --duration 120
"""
import argparse
import asyncio
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Any

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
class AddressInfo:
    """各OSCアドレスの最新値と統計"""
    latest_args: list = field(default_factory=list)
    count: int = 0
    first_seen: float = 0.0
    last_seen: float = 0.0


class CFChecker:
    """全 OSC メッセージを受信・記録"""

    def __init__(self, port: int, raw: bool, show_all: bool):
        self.port = port
        self.raw = raw
        self.show_all = show_all

        # address ごとの統計
        self.addresses: Dict[str, AddressInfo] = {}
        # デバイスごとのアドレス一覧
        self.device_addresses: Dict[str, set] = defaultdict(set)
        # 総メッセージ数
        self.total_msgs = 0

        self._dispatcher = Dispatcher()
        self._dispatcher.set_default_handler(self._on_any)

    def _on_any(self, address: str, *args):
        # CF以外をフィルタ (--all でなければ)
        if not self.show_all and not address.startswith("/CF"):
            return

        now = time.time()
        self.total_msgs += 1

        # アドレスごとの記録
        if address not in self.addresses:
            self.addresses[address] = AddressInfo(first_seen=now)
        info = self.addresses[address]
        info.latest_args = list(args)
        info.count += 1
        info.last_seen = now

        # デバイスID抽出
        parts = address.strip("/").split("/", 1)
        if len(parts) >= 1:
            self.device_addresses[parts[0]].add(address)

        # raw モード: 全メッセージ即時表示
        if self.raw:
            # 引数の型と値を表示
            arg_strs = []
            for a in args:
                if isinstance(a, float):
                    arg_strs.append(f"{a:+.6f} (float)")
                elif isinstance(a, int):
                    arg_strs.append(f"{a} (int)")
                elif isinstance(a, str):
                    arg_strs.append(f'"{a}" (str)')
                else:
                    arg_strs.append(f"{a!r} ({type(a).__name__})")

            elapsed = now - self._start_time if hasattr(self, '_start_time') else 0
            print(f"  [{elapsed:6.1f}s] {address}  →  {', '.join(arg_strs)}")

    def set_start_time(self, t: float):
        self._start_time = t

    async def start(self):
        server = AsyncIOOSCUDPServer(
            ("0.0.0.0", self.port), self._dispatcher, asyncio.get_event_loop()
        )
        transport, _ = await server.create_serve_endpoint()
        return transport


def print_address_table(checker: CFChecker, elapsed: float):
    """全アドレスの一覧を表形式で表示"""
    if not checker.addresses:
        print(f"[{elapsed:.0f}s] 受信待ち...")
        return

    # デバイスごとにグループ化
    for dev_id in sorted(checker.device_addresses.keys()):
        addrs = sorted(checker.device_addresses[dev_id])
        print(f"  ── {dev_id} ({len(addrs)} addresses) ──")
        for addr in addrs:
            info = checker.addresses[addr]
            age = time.time() - info.last_seen
            alive = "●" if age < 5.0 else "○"

            # パラメータ名を短縮表示
            param = addr.split("/", 2)[-1] if addr.count("/") >= 2 else addr

            # 値の表示
            val_str = ""
            for a in info.latest_args:
                if isinstance(a, float):
                    val_str += f"{a:+.6f} "
                elif isinstance(a, int):
                    val_str += f"{a} "
                elif isinstance(a, str):
                    val_str += f'"{a}" '
                else:
                    val_str += f"{a!r} "

            print(
                f"    {alive} {param:<35s}  "
                f"= {val_str:<20s}  "
                f"(n={info.count})"
            )
    print()


async def run_check(port: int, duration: float, raw: bool, show_all: bool):
    checker = CFChecker(port, raw, show_all)
    transport = await checker.start()

    start = time.time()
    checker.set_start_time(start)

    filter_desc = "全OSC" if show_all else "/CF* のみ"
    mode_desc = "RAW (全メッセージ表示)" if raw else "サマリー (3秒ごと)"

    print()
    print("=" * 70)
    print(f"  CF 受信チェック — port {port}")
    print(f"  モード: {mode_desc}")
    print(f"  フィルタ: {filter_desc}")
    print(f"  {duration:.0f}秒間モニタリング... (Ctrl+C で終了)")
    print("=" * 70)
    print()

    last_summary = 0

    try:
        while (time.time() - start) < duration:
            await asyncio.sleep(1.0)
            elapsed = int(time.time() - start)

            # raw モードでないときは 3秒ごとにサマリー
            if not raw and elapsed - last_summary >= 3:
                last_summary = elapsed
                print(f"[{elapsed:4d}s] ─── total msgs: {checker.total_msgs} ───")
                print_address_table(checker, elapsed)

            # raw モードでも 10秒ごとに軽いサマリー
            if raw and elapsed - last_summary >= 10:
                last_summary = elapsed
                n_addr = len(checker.addresses)
                n_dev = len(checker.device_addresses)
                print(
                    f"\n  --- [{elapsed}s] {checker.total_msgs} msgs, "
                    f"{n_dev} devices, {n_addr} unique addresses ---\n"
                )

    except asyncio.CancelledError:
        pass

    transport.close()

    # ===== サマリー =====
    print()
    print("=" * 70)
    print("  結果サマリー")
    print("=" * 70)

    if not checker.addresses:
        print("  ! デバイスから受信なし。確認事項:")
        print(f"    - CFデバイスの送信先が 10.0.0.200:{port} になっているか")
        print(f"    - ファイアウォールで UDP {port} が開いているか")
        print(f"    - CFデバイスが起動して計測中か")
        print()
        return 1

    print(f"  総メッセージ数: {checker.total_msgs}")
    print(f"  検出デバイス数: {len(checker.device_addresses)}")
    print(f"  ユニークアドレス数: {len(checker.addresses)}")
    print()

    # 全アドレス最終状態
    print("  全アドレス一覧:")
    print_address_table(checker, time.time() - start)

    return 0


def main():
    parser = argparse.ArgumentParser(description="CF device OSC reception check")
    parser.add_argument("--port", type=int, default=8000,
                        help="OSC listen port (default: 8000)")
    parser.add_argument("--duration", type=float, default=60,
                        help="Monitor duration in seconds (default: 60)")
    parser.add_argument("--raw", action="store_true",
                        help="Show every received message with types")
    parser.add_argument("--all", dest="show_all", action="store_true",
                        help="Show all OSC addresses, not just /CF*")
    args = parser.parse_args()

    try:
        rc = asyncio.run(run_check(args.port, args.duration, args.raw, args.show_all))
    except KeyboardInterrupt:
        print("\n中断しました")
        rc = 0

    sys.exit(rc)


if __name__ == "__main__":
    main()
