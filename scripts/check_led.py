#!/usr/bin/env python3
"""
LED点灯チェック - デバイス上で実行

pca9685_osc_led_server.py が起動していなければ自動起動し、
OSC経由でLEDのフェードアップ→保持→フェードダウンを行い動作確認する。

使い方:
    uv run python scripts/check_led.py
    uv run python scripts/check_led.py --bus 1
    uv run python scripts/check_led.py --host 127.0.0.1 --port 9000
    uv run python scripts/check_led.py --max-brightness 0.5
"""

import argparse
import os
import subprocess
import sys
import time

from pythonosc import udp_client


def is_led_server_running() -> bool:
    """pca9685_osc_led_server.py が起動しているか確認"""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "pca9685_osc_led_server"],
            capture_output=True, text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def start_led_server(port: int, bus: int) -> bool:
    """pca9685_osc_led_server.py をバックグラウンドで起動"""
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    server_script = os.path.join(script_dir, "pca9685_osc_led_server.py")

    if not os.path.exists(server_script):
        print(f"[FAIL] サーバースクリプトが見つかりません: {server_script}")
        return False

    cmd = [sys.executable, server_script, "--port", str(port), "--bus", str(bus)]
    print(f"              cmd: {' '.join(cmd)}")

    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # サーバー起動待ち
        time.sleep(1.5)

        if is_led_server_running():
            return True
        else:
            print("[FAIL] サーバーが起動しませんでした")
            return False
    except Exception as e:
        print(f"[FAIL] サーバー起動エラー: {e}")
        return False


def check_led(host: str, port: int, bus: int, max_brightness: float, steps: int, duration: float):
    """LEDフェードアップ→保持→フェードダウンを実行"""

    print(f"[LED CHECK] Target: {host}:{port}")
    print(f"[LED CHECK] I2C bus: {bus}")
    print(f"[LED CHECK] Max brightness: {max_brightness}, Steps: {steps}, Duration: {duration}s")
    print()

    # --- Step 0: サーバー起動チェック ---
    print("[LED CHECK] Step 0: pca9685_osc_led_server 起動確認...")
    if is_led_server_running():
        print("[OK] サーバーは既に起動済み")
    else:
        print("[WARN] サーバーが起動していません → 自動起動します")
        if not start_led_server(port, bus):
            return False
        print(f"[OK] サーバーを起動しました (port={port}, bus={bus})")
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
    parser.add_argument("--bus", type=int, default=1, help="I2Cバス番号 (default: 1)")
    parser.add_argument("--max-brightness", type=float, default=1.0, help="最大輝度 0.0-1.0 (default: 1.0)")
    parser.add_argument("--steps", type=int, default=20, help="フェードステップ数 (default: 20)")
    parser.add_argument("--duration", type=float, default=1.0, help="フェード時間（秒） (default: 1.0)")
    args = parser.parse_args()

    ok = check_led(args.host, args.port, args.bus, args.max_brightness, args.steps, args.duration)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
