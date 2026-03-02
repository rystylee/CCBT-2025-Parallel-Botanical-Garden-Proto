#!/usr/bin/env python3
"""
音声出力チェック - デバイス上で実行

TTS/LLMに依存せず、シンプルなテストトーン（サイン波）を生成し、
tinyplayで再生してスピーカーの動作を確認する。

前提:
    tinyplay コマンドが利用可能

使い方:
    uv run python scripts/check_audio.py
    uv run python scripts/check_audio.py --freq 440 --duration 2
    uv run python scripts/check_audio.py --card 0 --device 1
"""

import argparse
import math
import os
import struct
import subprocess
import sys
import tempfile


def generate_test_tone_wav(
    filepath: str,
    freq: float = 440.0,
    duration: float = 1.5,
    sample_rate: int = 32000,
    channels: int = 2,
    amplitude: float = 0.3,
):
    """シンプルなサイン波WAVファイルを生成"""

    num_samples = int(sample_rate * duration)
    bits_per_sample = 16
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    data_size = num_samples * channels * (bits_per_sample // 8)
    max_val = 32767

    # フェードイン/アウト（クリックノイズ防止）
    fade_samples = int(sample_rate * 0.05)  # 50ms

    with open(filepath, "wb") as f:
        # WAV header
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")

        # fmt chunk
        f.write(b"fmt ")
        f.write(struct.pack("<I", 16))  # chunk size
        f.write(struct.pack("<H", 1))  # PCM format
        f.write(struct.pack("<H", channels))
        f.write(struct.pack("<I", sample_rate))
        f.write(struct.pack("<I", byte_rate))
        f.write(struct.pack("<H", block_align))
        f.write(struct.pack("<H", bits_per_sample))

        # data chunk
        f.write(b"data")
        f.write(struct.pack("<I", data_size))

        for i in range(num_samples):
            # Sine wave
            t = i / sample_rate
            value = amplitude * math.sin(2.0 * math.pi * freq * t)

            # Fade in/out envelope
            if i < fade_samples:
                value *= i / fade_samples
            elif i > num_samples - fade_samples:
                value *= (num_samples - i) / fade_samples

            sample = int(value * max_val)
            sample = max(-max_val, min(max_val, sample))

            # Write to all channels
            for _ in range(channels):
                f.write(struct.pack("<h", sample))


def check_audio(card: int, device: int, freq: float, duration: float, sample_rate: int, channels: int):
    """テストトーンを生成してtinyplayで再生"""

    print(f"[AUDIO CHECK] Card: {card}, Device: {device}")
    print(f"[AUDIO CHECK] Freq: {freq}Hz, Duration: {duration}s, Rate: {sample_rate}Hz, Ch: {channels}")
    print()

    # --- Step 1: tinyplayの存在確認 ---
    print("[AUDIO CHECK] Step 1: tinyplay コマンドの確認...")
    try:
        result = subprocess.run(["which", "tinyplay"], capture_output=True, text=True)
        if result.returncode != 0:
            print("[FAIL] tinyplay が見つかりません")
            print("       → apt install tinyalsa-utils でインストールしてください")
            return False
        print(f"[OK] tinyplay found: {result.stdout.strip()}")
    except FileNotFoundError:
        print("[FAIL] which コマンドが見つかりません")
        return False

    # --- Step 2: テストトーン生成 ---
    print("[AUDIO CHECK] Step 2: テストトーンWAV生成...")
    tmp_path = os.path.join(tempfile.gettempdir(), "check_audio_tone.wav")
    try:
        generate_test_tone_wav(
            tmp_path,
            freq=freq,
            duration=duration,
            sample_rate=sample_rate,
            channels=channels,
        )
        file_size = os.path.getsize(tmp_path)
        print(f"[OK] WAVファイル生成: {tmp_path} ({file_size} bytes)")
    except Exception as e:
        print(f"[FAIL] WAVファイル生成エラー: {e}")
        return False

    # --- Step 3: tinyplayで再生 ---
    print(f"[AUDIO CHECK] Step 3: tinyplay で再生中 ({freq}Hz, {duration}秒)...")
    try:
        cmd = ["tinyplay", f"-D{card}", f"-d{device}", tmp_path]
        print(f"              cmd: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 5)
        if result.returncode != 0:
            print(f"[FAIL] tinyplay エラー (exit code: {result.returncode})")
            if result.stderr:
                print(f"       stderr: {result.stderr.strip()}")
            return False
        print("[OK] tinyplay 再生完了")
    except subprocess.TimeoutExpired:
        print("[WARN] tinyplay タイムアウト（再生は完了した可能性あり）")
    except FileNotFoundError:
        print("[FAIL] tinyplay が実行できません")
        return False
    except Exception as e:
        print(f"[FAIL] tinyplay 実行エラー: {e}")
        return False
    finally:
        # Cleanup
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    print()
    print("[OK] 音声出力チェック完了 ✓")
    print("     → スピーカーからテストトーンが聞こえたことを確認してください")
    return True


def main():
    parser = argparse.ArgumentParser(description="音声出力チェック（デバイス上で実行）")
    parser.add_argument("--card", type=int, default=0, help="ALSAカード番号 (default: 0)")
    parser.add_argument("--device", type=int, default=1, help="ALSAデバイス番号 (default: 1)")
    parser.add_argument("--freq", type=float, default=440.0, help="テストトーン周波数Hz (default: 440)")
    parser.add_argument("--duration", type=float, default=1.5, help="再生時間（秒） (default: 1.5)")
    parser.add_argument("--sample-rate", type=int, default=32000, help="サンプルレートHz (default: 32000)")
    parser.add_argument("--channels", type=int, default=2, help="チャンネル数 (default: 2)")
    args = parser.parse_args()

    ok = check_audio(args.card, args.device, args.freq, args.duration, args.sample_rate, args.channels)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
