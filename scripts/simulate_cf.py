#!/usr/bin/env python3
"""
CF デバイスシミュレーター (テスト用送信)

実機 (10.0.0.211/212) が無い環境でも受信チェックできるように、
CFデバイスと同じ OSC メッセージを送信する。

使い方:
  # ローカルテスト (自分自身に送信)
  uv run python scripts/simulate_cf.py

  # 送信先・ポート指定
  uv run python scripts/simulate_cf.py --target 10.0.0.200 --port 8000

  # CF2 だけシミュレート
  uv run python scripts/simulate_cf.py --cf-id CF2

別ターミナルで check_cf.py を動かして確認:
  uv run python scripts/check_cf.py --port 8000
"""
import argparse
import math
import time
import sys

from pythonosc import udp_client


def simulate(target: str, port: int, cf_id: str, interval: float, cycles: int):
    client = udp_client.SimpleUDPClient(target, port)

    print(f"CF simulator: {cf_id} → {target}:{port} (interval={interval}s)")
    print(f"Sending {cycles} cycles... (Ctrl+C to stop)")
    print()

    update_every = 10  # N回に1回 "updated" にする (≒計測周期シミュレーション)

    for i in range(cycles):
        # サイン波で PFI change をシミュレート (-1.0 ~ 1.0)
        t = i / max(1, cycles)
        pfi_change = math.sin(t * math.pi * 4)  # 2周期分

        # class: change を 7段階に量子化
        # -1.0→0, 0→3, 1.0→6
        pfi_class = int(round((pfi_change + 1.0) / 2.0 * 6.0))
        pfi_class = max(0, min(6, pfi_class))

        # flag
        flag = "updated" if (i % update_every == 0) else "same"

        # OSC 送信
        client.send_message(f"/{cf_id}/PFI_degree_of_change", pfi_change)
        client.send_message(f"/{cf_id}/PFI_degree_of_change_class", pfi_class)
        client.send_message(f"/{cf_id}/flag", flag)

        marker = " ★ UPDATED" if flag == "updated" else ""
        print(
            f"  [{i+1:4d}] /{cf_id}  "
            f"change={pfi_change:+.4f}  "
            f"class={pfi_class}  "
            f"flag={flag}{marker}"
        )

        time.sleep(interval)

    print("\nDone.")


def main():
    parser = argparse.ArgumentParser(description="CF device OSC simulator")
    parser.add_argument("--target", type=str, default="127.0.0.1",
                        help="Target IP (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000,
                        help="Target OSC port (default: 8000)")
    parser.add_argument("--cf-id", type=str, default="CF1",
                        choices=["CF1", "CF2"],
                        help="CF device ID (default: CF1)")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="Send interval in seconds (default: 1.0)")
    parser.add_argument("--cycles", type=int, default=60,
                        help="Number of send cycles (default: 60)")
    args = parser.parse_args()

    try:
        simulate(args.target, args.port, args.cf_id, args.interval, args.cycles)
    except KeyboardInterrupt:
        print("\n中断しました")


if __name__ == "__main__":
    main()
