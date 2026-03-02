#!/usr/bin/env python3
"""
全機能一括チェック - デバイス上で実行

以下の4機能を順番にテストし、結果をサマリー表示する:
  1. LED点灯（OSC → PCA9685）
  2. 音声出力（tinyplay テストトーン）
  3. LLMテキスト生成（StackFlow LLM）
  4. TTS音声合成（MeloTTS OpenAI互換API）

使い方:
    uv run python scripts/check_all.py
    uv run python scripts/check_all.py --skip-led          # LED以外をテスト
    uv run python scripts/check_all.py --skip-audio        # 音声出力以外をテスト
    uv run python scripts/check_all.py --play-tts          # TTS結果も再生
    uv run python scripts/check_all.py --lang en           # 英語でテスト
    uv run python scripts/check_all.py --only llm          # LLMだけテスト
    uv run python scripts/check_all.py --only led,tts      # LED+TTSだけテスト
"""

import argparse
import subprocess
import sys
import time

CHECKS = ["led", "audio", "llm", "tts"]


def run_check(name: str, cmd: list, timeout: float = 60.0) -> bool:
    """サブプロセスでチェックスクリプトを実行"""
    try:
        result = subprocess.run(
            cmd,
            capture_output=False,  # 標準出力をそのまま表示
            timeout=timeout,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[FAIL] {name}: タイムアウト ({timeout}秒)")
        return False
    except FileNotFoundError:
        print(f"[FAIL] {name}: コマンドが見つかりません: {cmd[0]}")
        return False
    except Exception as e:
        print(f"[FAIL] {name}: 実行エラー: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="全機能一括チェック（デバイス上で実行）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--lang", type=str, default="ja", choices=["ja", "en", "zh"],
                        help="テスト言語 (default: ja)")
    parser.add_argument("--skip-led", action="store_true", help="LEDチェックをスキップ")
    parser.add_argument("--skip-audio", action="store_true", help="音声出力チェックをスキップ")
    parser.add_argument("--skip-llm", action="store_true", help="LLMチェックをスキップ")
    parser.add_argument("--skip-tts", action="store_true", help="TTSチェックをスキップ")
    parser.add_argument("--play-tts", action="store_true", help="TTS生成結果をtinyplayで再生")
    parser.add_argument("--only", type=str, default=None,
                        help="指定した機能だけテスト (カンマ区切り: led,audio,llm,tts)")
    parser.add_argument("--led-host", type=str, default="127.0.0.1", help="LED OSCサーバーホスト")
    parser.add_argument("--led-port", type=int, default=9000, help="LED OSCサーバーポート")
    parser.add_argument("--led-bus", type=int, default=1, help="LED I2Cバス番号 (default: 1)")
    args = parser.parse_args()

    # テスト対象の決定
    if args.only:
        targets = [c.strip() for c in args.only.split(",")]
        for t in targets:
            if t not in CHECKS:
                print(f"[ERROR] 不明なチェック名: {t} (使用可能: {', '.join(CHECKS)})")
                sys.exit(1)
    else:
        targets = []
        if not args.skip_led:
            targets.append("led")
        if not args.skip_audio:
            targets.append("audio")
        if not args.skip_llm:
            targets.append("llm")
        if not args.skip_tts:
            targets.append("tts")

    if not targets:
        print("[ERROR] テスト対象がありません")
        sys.exit(1)

    # ヘッダー
    print("=" * 60)
    print("  BI デバイス機能チェック")
    print(f"  テスト対象: {', '.join(targets)}")
    print(f"  言語: {args.lang}")
    print("=" * 60)
    print()

    results = {}

    # --- 1. LED ---
    if "led" in targets:
        print("─" * 60)
        print("  [1/4] LED 点灯チェック")
        print("─" * 60)
        cmd = [
            sys.executable, "scripts/check_led.py",
            "--host", args.led_host,
            "--port", str(args.led_port),
            "--bus", str(args.led_bus),
        ]
        results["LED点灯"] = run_check("LED", cmd, timeout=15)
        print()
        time.sleep(0.5)

    # --- 2. Audio ---
    if "audio" in targets:
        print("─" * 60)
        print("  [2/4] 音声出力チェック (tinyplay)")
        print("─" * 60)
        cmd = [sys.executable, "scripts/check_audio.py"]
        results["音声出力"] = run_check("Audio", cmd, timeout=15)
        print()
        time.sleep(0.5)

    # --- 3. LLM ---
    if "llm" in targets:
        print("─" * 60)
        print("  [3/4] LLM テキスト生成チェック")
        print("─" * 60)
        cmd = [
            sys.executable, "scripts/check_llm.py",
            "--lang", args.lang,
        ]
        results["LLMテキスト生成"] = run_check("LLM", cmd, timeout=60)
        print()
        time.sleep(0.5)

    # --- 4. TTS ---
    if "tts" in targets:
        print("─" * 60)
        print("  [4/4] TTS 音声合成チェック")
        print("─" * 60)
        cmd = [
            sys.executable, "scripts/check_tts.py",
            "--lang", args.lang,
        ]
        if args.play_tts:
            cmd.append("--play")
        results["TTS音声合成"] = run_check("TTS", cmd, timeout=30)
        print()

    # --- サマリー ---
    print("=" * 60)
    print("  チェック結果サマリー")
    print("=" * 60)
    print()

    all_ok = True
    for name, ok in results.items():
        status = "✓ OK" if ok else "✗ FAIL"
        mark = "  " if ok else "→ "
        print(f"  {mark}{name:20s} [{status}]")
        if not ok:
            all_ok = False

    print()
