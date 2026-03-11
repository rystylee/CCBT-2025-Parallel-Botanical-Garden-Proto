#!/usr/bin/env python3
"""Test script for soft prefix LED performance.

Send OSC message to trigger LED fade performance via /bi/soft_prefix_update endpoint.

Usage:
    python scripts/test_soft_prefix_led.py
    python scripts/test_soft_prefix_led.py --fade-up 3.0 --fade-down 1.5
    python scripts/test_soft_prefix_led.py --host 10.0.0.61 --port 8000
"""

import argparse
import time

from pythonosc import udp_client


def parse_args():
    parser = argparse.ArgumentParser(description="Test soft prefix LED performance")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Target host IP address")
    parser.add_argument("--port", type=int, default=8000, help="Target OSC port")
    parser.add_argument("--fade-up", type=float, default=2.0, help="Fade up duration in seconds (0.0 -> 1.0)")
    parser.add_argument("--fade-down", type=float, default=2.0, help="Fade down duration in seconds (1.0 -> 0.0)")
    parser.add_argument("--repeat", type=int, default=1, help="Number of times to repeat the test")
    parser.add_argument("--interval", type=float, default=5.0, help="Interval between repeats in seconds")
    return parser.parse_args()


def main():
    args = parse_args()

    # Create OSC client
    client = udp_client.SimpleUDPClient(args.host, args.port)

    print(f"Sending OSC to {args.host}:{args.port}")
    print(f"Endpoint: /bi/soft_prefix_update")
    print(f"Parameters: fade_up={args.fade_up}s, fade_down={args.fade_down}s")
    print(f"Repeats: {args.repeat} times with {args.interval}s interval")
    print()

    for i in range(args.repeat):
        print(f"[{i + 1}/{args.repeat}] Sending soft_prefix_update...")
        client.send_message("/bi/soft_prefix_update", [args.fade_up, args.fade_down])
        print(f"  → Sent: /bi/soft_prefix_update {args.fade_up} {args.fade_down}")

        if i < args.repeat - 1:
            print(f"  → Waiting {args.interval}s until next send...")
            time.sleep(args.interval)

    print()
    print("✓ Test completed")


if __name__ == "__main__":
    main()
