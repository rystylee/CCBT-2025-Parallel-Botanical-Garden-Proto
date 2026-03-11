#!/usr/bin/env python3
"""
CF (クロロフィル蛍光) デバイス受信チェック

10.0.0.200 上で実行し、CF1 (10.0.0.211) / CF2 (10.0.0.212) からの
OSC メッセージを受信できているか確認する。

使い方:
  # デフォルト (port 8000, 60秒)
  uv run python scripts/check_cf.py

  # ポート・時間指定
  uv run python scripts/check_cf.py --port 8000 --duration 120

  # 詳細ログ (全受信メッセージ)
  uv run python scripts/check_cf.py --verbose
"""
import argparse
import asyncio
import sys
import time

from loguru import logger

# ── loguru 設定 ──
logger.remove()
logger.add(sys.stderr, level="DEBUG", format="{time:HH:mm:ss} | {level:<7} | {message}")

# ── プロジェクトの CFOscReceiver を使う ──
sys.path.insert(0, ".")
from input_controller.cf_receiver import CFOscReceiver, CF_CLASS_LABELS


async def run_check(port: int, duration: float, verbose: bool):
    receiver = CFOscReceiver(port=port, listen_ip="0.0.0.0")
    await receiver.start()

    print()
    print("=" * 60)
    print(f"  CF 受信チェック — port {port}")
    print(f"  CF1: 10.0.0.211 → ここ (10.0.0.200:{port})")
    print(f"  CF2: 10.0.0.212 → ここ (10.0.0.200:{port})")
    print(f"  {duration}秒間モニタリング... (Ctrl+C で終了)")
    print("=" * 60)
    print()

    start = time.time()
    last_print = 0
    cf1_count = 0
    cf2_count = 0

    try:
        while (time.time() - start) < duration:
            await asyncio.sleep(1.0)

            elapsed = int(time.time() - start)
            snap1 = receiver.get("CF1")
            snap2 = receiver.get("CF2")

            # 受信カウント更新
            alive1 = receiver.is_alive("CF1", max_age=5.0)
            alive2 = receiver.is_alive("CF2", max_age=5.0)

            if alive1:
                cf1_count += 1
            if alive2:
                cf2_count += 1

            # 3秒ごとにステータス表示
            if elapsed - last_print >= 3 or verbose:
                last_print = elapsed

                print(f"[{elapsed:4d}s] ──────────────────────────────────")

                # CF1
                status1 = "● ALIVE" if alive1 else "○ NO DATA"
                cls1_label = CF_CLASS_LABELS.get(snap1.pfi_class, "?")
                print(
                    f"  CF1: {status1}  "
                    f"change={snap1.pfi_change:+.4f}  "
                    f"class={snap1.pfi_class} ({cls1_label})  "
                    f"flag={snap1.flag}  "
                    f"updates={snap1.update_count}"
                )

                # CF2
                status2 = "● ALIVE" if alive2 else "○ NO DATA"
                cls2_label = CF_CLASS_LABELS.get(snap2.pfi_class, "?")
                print(
                    f"  CF2: {status2}  "
                    f"change={snap2.pfi_change:+.4f}  "
                    f"class={snap2.pfi_class} ({cls2_label})  "
                    f"flag={snap2.flag}  "
                    f"updates={snap2.update_count}"
                )
                print()

    except asyncio.CancelledError:
        pass

    await receiver.stop()

    # サマリー
    print()
    print("=" * 60)
    print("  結果サマリー")
    print("=" * 60)
    total = int(time.time() - start)

    snap1 = receiver.get("CF1")
    snap2 = receiver.get("CF2")

    for cf_id, snap, count in [("CF1", snap1, cf1_count), ("CF2", snap2, cf2_count)]:
        if snap.timestamp > 0:
            print(f"  {cf_id}: OK — {snap.update_count} 回更新, "
                  f"最終 change={snap.pfi_change:+.4f}, class={snap.pfi_class}")
        else:
            print(f"  {cf_id}: NG — 受信なし")

    print()

    if snap1.timestamp == 0 and snap2.timestamp == 0:
        print("  ! どちらも受信なし。確認事項:")
        print(f"    - CFデバイスの送信先が 10.0.0.200:{port} になっているか")
        print(f"    - ファイアウォールで UDP {port} が開いているか")
        print(f"    - CFデバイスが起動して計測中か")
        print()
        return 1

    return 0


def main():
    parser = argparse.ArgumentParser(description="CF device OSC reception check")
    parser.add_argument("--port", type=int, default=8000,
                        help="OSC listen port (default: 8000)")
    parser.add_argument("--duration", type=float, default=60,
                        help="Monitor duration in seconds (default: 60)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print every second instead of every 3s")
    args = parser.parse_args()

    try:
        rc = asyncio.run(run_check(args.port, args.duration, args.verbose))
    except KeyboardInterrupt:
        print("\n中断しました")
        rc = 0

    sys.exit(rc)


if __name__ == "__main__":
    main()
