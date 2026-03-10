#!/usr/bin/env python3
"""植物センサー入力テスト

CFデバイスのOSC入力と、AEセンサーのCSV読み取りを個別にテストする。

使い方:
    # CFデバイス模擬送信 (別ターミナルで processor を起動しておく)
    python3 test_sensor_input.py cf

    # AEセンサーCSV読み取りテスト (processor不要)
    python3 test_sensor_input.py ae

    # 両方テスト
    python3 test_sensor_input.py all
"""

import argparse
import csv
import os
import sys
import time
from pathlib import Path


def test_cf(target_ip: str = "127.0.0.1", target_port: int = 8000):
    """CFデバイスの模擬OSCメッセージを送信"""
    from pythonosc.udp_client import SimpleUDPClient

    client = SimpleUDPClient(target_ip, target_port)
    print(f"[CF test] 送信先: {target_ip}:{target_port}")
    print()

    # ① PFI変化度合い (float)
    test_values = [
        ("/CF01/PFI_degree_of_change", -0.8, "much worse → sp=0.0"),
        ("/CF01/PFI_degree_of_change", -0.3, "worse → sp=1e-4"),
        ("/CF01/PFI_degree_of_change",  0.2, "better → sp=1e-3"),
        ("/CF01/PFI_degree_of_change",  0.7, "much better → sp=1e-2"),
    ]

    for addr, val, desc in test_values:
        client.send_message(addr, float(val))
        print(f"  送信: {addr} = {val:+.1f}  ({desc})")
        time.sleep(0.3)

    print()

    # ② PFIクラス (int)
    class_tests = [
        ("/CF02/PFI_degree_of_change_class", 0, "getting much worse"),
        ("/CF02/PFI_degree_of_change_class", 3, "no change"),
        ("/CF02/PFI_degree_of_change_class", 6, "getting much better"),
    ]

    for addr, val, desc in class_tests:
        client.send_message(addr, int(val))
        print(f"  送信: {addr} = {val}  ({desc})")
        time.sleep(0.3)

    print()

    # ③ フラグ
    client.send_message("/CF01/flag", "updated")
    print(f"  送信: /CF01/flag = 'updated'")
    time.sleep(0.5)
    client.send_message("/CF01/flag", "same")
    print(f"  送信: /CF01/flag = 'same'")

    print()
    print("[CF test] ✅ 完了。processor側のログを確認してください。")


def test_ae(csv_dir: str = "./ae_csv"):
    """AEセンサーCSV読み取りテスト"""
    csv_path = Path(csv_dir)
    csv_path.mkdir(parents=True, exist_ok=True)

    # テスト用CSVを生成
    test_file = csv_path / "test_ae_data.csv"
    print(f"[AE test] テストCSV作成: {test_file}")

    rows = [
        {"Time (hr)": "0",   "Date": "2026/03/03 00:00:00", "AE": "0",   "AE1ch": "0",   "AE2ch": "0"},
        {"Time (hr)": "24",  "Date": "2026/03/04 00:00:00", "AE": "109", "AE1ch": "109", "AE2ch": "0"},
        {"Time (hr)": "48",  "Date": "2026/03/05 00:00:00", "AE": "98",  "AE1ch": "98",  "AE2ch": "0"},
        {"Time (hr)": "72",  "Date": "2026/03/06 00:00:00", "AE": "143", "AE1ch": "143", "AE2ch": "0"},
    ]

    with open(test_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["Time (hr)", "Date", "AE", "AE1ch", "AE2ch"],
                                quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    print(f"  データ: {len(rows)}行 (最終行 AE=143)")
    print()

    # 読み取りテスト
    print("[AE test] CSV読み取りテスト:")
    try:
        with open(test_file, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            all_rows = list(reader)

        last = all_rows[-1]
        ae_val = float(last["AE"])
        date_str = last["Date"]
        max_count = 200.0
        normalized = min(1.0, ae_val / max_count)

        print(f"  最新行: Date={date_str}, AE={ae_val:.0f}")
        print(f"  正規化: {ae_val:.0f} / {max_count:.0f} = {normalized:.3f}")

        # soft_prefix 変換テスト
        import base64, struct

        def f32_to_bf16_u16(x):
            return (struct.unpack("<I", struct.pack("<f", x))[0] >> 16) & 0xFFFF

        if normalized < 0.25:
            sp_val = 0.0
        elif normalized < 0.50:
            sp_val = 1e-4
        elif normalized < 0.75:
            sp_val = 1e-3
        else:
            sp_val = 1e-2

        print(f"  soft_prefix値: {sp_val} (normalized={normalized:.3f})")
        print()
        print("[AE test] ✅ 完了。")
        print(f"  テストCSVは {csv_path}/ に残してあります。")
        print(f"  processor起動中なら30秒以内に自動検出されます。")

    except Exception as e:
        print(f"[AE test] ❌ 失敗: {e}")


def test_all():
    print("=" * 50)
    print("植物センサー入力テスト")
    print("=" * 50)
    print()

    print("--- AEセンサー (CSV読み取り) ---")
    test_ae()
    print()

    print("--- CFデバイス (OSC模擬送信) ---")
    print("※ processor が起動していることを確認してください")
    print("  python3 plant_sensor_processor.py --dry-run")
    print()
    test_cf()


def main():
    parser = argparse.ArgumentParser(description="植物センサー入力テスト")
    parser.add_argument("test", choices=["cf", "ae", "all"], help="テスト対象")
    parser.add_argument("--target-ip", default="127.0.0.1", help="CF送信先IP")
    parser.add_argument("--target-port", type=int, default=8000, help="CF送信先ポート")
    parser.add_argument("--csv-dir", default="./ae_csv", help="AE CSVフォルダ")
    args = parser.parse_args()

    if args.test == "cf":
        test_cf(args.target_ip, args.target_port)
    elif args.test == "ae":
        test_ae(args.csv_dir)
    elif args.test == "all":
        test_all()


if __name__ == "__main__":
    main()
