#!/usr/bin/env python3
"""
LED点灯チェック - デバイス上で実行

pca9685_osc_led_server.py が起動している前提で、
OSC経由でLEDのフェードアップ→保持→フェードダウンを行い動作確認する。

前提:
    pca9685_osc_led_server.py がlocalhost:9000で起動済み

使い方:
    uv run python scripts/check_led.py
    uv run python scripts/check_led.py --host 127.0.0.1 --port 9000
    uv run python scripts/check_led.py --max-brightness 0.5
"""

import argparse
import sys
import time

from pythonosc import udp_client


def check_led(host: str, port: int, max_brightness: float, steps: int, duration: float):
    """LEDフェードアップ→保持→フェードダウンを実行"""

    print(f"[LED CHECK] Target: {host}:{port}")
    print(f"[LED CHECK] Max brightness: {max_brightness}, Steps: {steps}, Duration: {duration}s")
    print()

    try:
        client = udp_client.SimpleUDPClient(host, port)
    except Exception as e:
        print(f"[FAIL] OSCクライアント作成失敗: {e}")
        return False

    dt = duration / steps

    # --- Phase 1: フェードアップ ---
    print("[LED CHECK] Phase 1: フェードアップ...")
    try:
        for i in range(steps + 1):
            value = (i / steps) * max_brightness
            client.send_message("/led", [value])
            if i < steps:
                time.sleep(dt)
        print(f"[OK] フェードアップ完了 (0.0 → {max_brightness})")
    except Exception as e:
        print(f"[FAIL] フェードアップ中にエラー: {e}")
        return False

    # --- Phase 2: 保持 ---
    print("[LED CHECK] Phase 2: 1秒間保持...")
    time.sleep(1.0)

    # --- Phase 3: フェードダウン ---
    print("[LED CHECK] Phase 3: フェードダウン...")
    try:
        for i in range(steps, -1, -1):
            value = (i / steps) * max_brightness
            client.send_message("/led", [value])
            if i > 0:
                time.sleep(dt)
        print(f"[OK] フェードダウン完了 ({max_brightness} → 0.0)")
    except Exception as e:
        print(f"[FAIL] フェードダウン中にエラー: {e}")
        return False

    # --- Phase 4: 確実にOFF ---
    try:
        client.send_message("/led", [0.0])
        client.send_message("/led/off", [])
    except Exception:
        pass

    print()
    print("[OK] LED チェック完了 ✓")
    print("     → LEDが光って消えたことを目視確認してください")
    return True


def main():
    parser = argparse.ArgumentParser(description="LED点灯チェック（デバイス上で実行）")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="LED OSCサーバーのホスト (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9000, help="LED OSCサーバーのポート (default: 9000)")
    parser.add_argument("--max-brightness", type=float, default=1.0, help="最大輝度 0.0-1.0 (default: 1.0)")
    parser.add_argument("--steps", type=int, default=20, help="フェードステップ数 (default: 20)")
    parser.add_argument("--duration", type=float, default=1.0, help="フェード時間（秒） (default: 1.0)")
    args = parser.parse_args()

    ok = check_led(args.host, args.port, args.max_brightness, args.steps, args.duration)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
