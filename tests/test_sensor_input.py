#!/usr/bin/env python3
"""植物センサー入力テスト

CFデバイスのOSC模擬送信と、AEセンサーCSV読み取りをテスト。
マトリクス変換の確認も含む。

使い方:
    python3 test_sensor_input.py cf       # CF模擬OSC送信
    python3 test_sensor_input.py ae       # AE CSV読み取り
    python3 test_sensor_input.py matrix   # マトリクス変換テーブル表示
    python3 test_sensor_input.py all      # 全部
"""

import argparse
import csv
import struct
import sys
import time
from pathlib import Path


def f32_to_bf16_u16(x: float) -> int:
    return (struct.unpack("<I", struct.pack("<f", x))[0] >> 16) & 0xFFFF


def test_matrix():
    """マトリクス変換テーブルを全パターン表示"""
    print("=== AE×CF → soft_prefix マトリクス ===")
    print()

    ae_thresholds = [0.33, 0.66]
    cf_thresholds = [-0.3, 0.3]
    matrix = {
        (0, 0): 1e-3, (0, 1): 3e-3, (0, 2): 7e-3,
        (1, 0): 3e-3, (1, 1): 7e-3, (1, 2): 1e-2,
        (2, 0): 7e-3, (2, 1): 1e-2, (2, 2): 1e-2,
    }
    ae_labels = ["AE低(<0.33)", "AE中(0.33~0.66)", "AE高(>0.66)"]
    cf_labels = ["CF悪化(<-0.3)", "CF安定(-0.3~0.3)", "CF良化(>0.3)"]

    print(f"{'':20s}  {cf_labels[0]:16s}  {cf_labels[1]:16s}  {cf_labels[2]:16s}")
    print("-" * 76)
    for ae_lv in range(3):
        row = f"{ae_labels[ae_lv]:20s}"
        for cf_lv in range(3):
            val = matrix[(ae_lv, cf_lv)]
            bf16 = f32_to_bf16_u16(val)
            row += f"  {val:.0e} (0x{bf16:04X})  "
        print(row)

    print()
    print("意味: 1e-3=収束的(韻律・反復)  →  1e-2=発散的(自由・逸脱)")
    print()

    # 具体例
    examples = [
        (0.1, -0.8, "AE静か + CF大幅悪化 → 植物が沈黙し衰退"),
        (0.1,  0.7, "AE静か + CF大幅良化 → 静寂の中から回復"),
        (0.5,  0.0, "AE中程度 + CF安定 → 通常の活動"),
        (0.8, -0.5, "AE高活性 + CF悪化 → ストレス下で必死"),
        (0.8,  0.8, "AE高活性 + CF大幅良化 → 最も活発"),
    ]

    print("--- 具体例 ---")
    for ae_norm, pfi, desc in examples:
        ae_lv = 0 if ae_norm < 0.33 else (1 if ae_norm < 0.66 else 2)
        cf_lv = 0 if pfi < -0.3 else (1 if pfi < 0.3 else 2)
        val = matrix[(ae_lv, cf_lv)]
        print(f"  AE={ae_norm:.1f} PFI={pfi:+.1f} → {val:.0e}  ({desc})")


def test_cf(target_ip: str = "127.0.0.1", target_port: int = 8000):
    """CFデバイスの模擬OSCメッセージを送信"""
    from pythonosc.udp_client import SimpleUDPClient

    client = SimpleUDPClient(target_ip, target_port)
    print(f"[CF test] 送信先: {target_ip}:{target_port}")
    print()

    # CF00: PFI float の各パターン
    cf00_tests = [
        ("/CF00/PFI_degree_of_change", -0.8, "悪化"),
        ("/CF00/PFI_degree_of_change",  0.0, "安定"),
        ("/CF00/PFI_degree_of_change",  0.7, "良化"),
    ]

    print("--- CF00 パターン ---")
    for addr, val, desc in cf00_tests:
        client.send_message(addr, float(val))
        print(f"  送信: {addr} = {val:+.1f}  ({desc})")
        time.sleep(0.5)

    client.send_message("/CF00/flag", "updated")
    print(f"  送信: /CF00/flag = 'updated'")
    time.sleep(1)

    print()

    # CF01: PFI class
    cf01_tests = [
        ("/CF01/PFI_degree_of_change_class", 0, "much worse"),
        ("/CF01/PFI_degree_of_change_class", 3, "no change"),
        ("/CF01/PFI_degree_of_change_class", 6, "much better"),
    ]

    print("--- CF01 パターン ---")
    for addr, val, desc in cf01_tests:
        client.send_message(addr, int(val))
        print(f"  送信: {addr} = {val}  ({desc})")
        time.sleep(0.5)

    client.send_message("/CF01/flag", "updated")
    print(f"  送信: /CF01/flag = 'updated'")

    print()
    print("[CF test] ✅ 完了。processor側のログを確認してください。")


def test_ae(csv_dir: str):
    """AEセンサーCSV読み取りテスト"""
    csv_path = Path(csv_dir)
    csv_path.mkdir(parents=True, exist_ok=True)

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

    print(f"  データ: {len(rows)}行")
    print()

    with open(test_file, encoding="utf-8-sig") as f:
        all_rows = list(csv.DictReader(f))

    last = all_rows[-1]
    ae_val = float(last["AE"])
    max_count = 200.0
    normalized = min(1.0, ae_val / max_count)

    print(f"  最終行: Date={last['Date']}, AE={ae_val:.0f}")
    print(f"  正規化: {ae_val:.0f} / {max_count:.0f} = {normalized:.3f}")

    ae_lv = 0 if normalized < 0.33 else (1 if normalized < 0.66 else 2)
    ae_labels = ["低", "中", "高"]
    print(f"  AEレベル: {ae_labels[ae_lv]} (マトリクスの行)")
    print()
    print(f"[AE test] ✅ 完了。{csv_path}/ にテストCSVを配置しました。")
    print(f"  processor起動中なら30秒以内に自動検出されます。")


def test_all():
    print("=" * 60)
    print("植物センサー入力テスト")
    print("=" * 60)
    print()

    test_matrix()
    print()

    print("--- AEセンサー (CSV読み取り) ---")
    csv_dir = str(Path(__file__).parent.parent / "ae_csv")
    test_ae(csv_dir)
    print()

    print("--- CFデバイス (OSC模擬送信) ---")
    print("※ processor が起動していることを確認してください:")
    print("  python3 plant_sensor_processor.py --dry-run")
    print()
    test_cf()


def main():
    parser = argparse.ArgumentParser(description="植物センサー入力テスト")
    parser.add_argument("test", choices=["cf", "ae", "matrix", "all"], help="テスト対象")
    parser.add_argument("--target-ip", default="127.0.0.1", help="CF送信先IP")
    parser.add_argument("--target-port", type=int, default=8000, help="CF送信先ポート")
    parser.add_argument("--csv-dir", default=None, help="AE CSVフォルダ")
    args = parser.parse_args()

    if args.test == "cf":
        test_cf(args.target_ip, args.target_port)
    elif args.test == "ae":
        csv_dir = args.csv_dir or str(Path(__file__).parent.parent / "ae_csv")
        test_ae(csv_dir)
    elif args.test == "matrix":
        test_matrix()
    elif args.test == "all":
        test_all()


if __name__ == "__main__":
    main()
