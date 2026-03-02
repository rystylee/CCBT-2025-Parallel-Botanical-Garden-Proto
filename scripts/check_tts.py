#!/usr/bin/env python3
"""
TTS音声合成チェック - デバイス上で実行

OpenAI互換TTS API (MeloTTS) に接続してWAVファイルを生成し、
音声合成が正常に動作するか確認する。
--play オプションでtinyplay再生も実行可能。

前提:
    StackFlow MeloTTS サービスが起動済み (systemctl status llm-melotts)
    OpenAI API サーバーが起動済み (systemctl status llm-openai-api)

使い方:
    uv run python scripts/check_tts.py
    uv run python scripts/check_tts.py --play
    uv run python scripts/check_tts.py --text "テスト音声" --play
    uv run python scripts/check_tts.py --lang en --text "Hello world" --play
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time

# 言語別デフォルト設定
DEFAULT_SETTINGS = {
    "ja": {"model": "melotts-ja-jp", "text": "こんにちは、音声合成のテストです。"},
    "en": {"model": "melotts-en-us", "text": "Hello, this is a text to speech test."},
    "zh": {"model": "melotts-zh-cn", "text": "你好，这是语音合成测试。"},
}


def check_tts(
    api_url: str,
    lang: str,
    model: str,
    text: str,
    play: bool,
    card: int,
    device: int,
    ffmpeg_convert: bool,
):
    """TTS APIでWAVを生成し、オプションで再生"""

    settings = DEFAULT_SETTINGS.get(lang, DEFAULT_SETTINGS["ja"])
    if model is None:
        model = settings["model"]
    if text is None:
        text = settings["text"]

    print(f"[TTS CHECK] API: {api_url}")
    print(f"[TTS CHECK] Model: {model}")
    print(f"[TTS CHECK] Text: {text}")
    print(f"[TTS CHECK] Play: {play}")
    print()

    tmp_dir = tempfile.gettempdir()
    raw_wav = os.path.join(tmp_dir, "check_tts_raw.wav")
    final_wav = os.path.join(tmp_dir, "check_tts_final.wav")

    # --- Step 1: API接続確認 ---
    print("[TTS CHECK] Step 1: OpenAI互換API接続確認...")
    try:
        from openai import OpenAI

        client = OpenAI(api_key="sk-", base_url=api_url)
        print(f"[OK] OpenAI クライアント作成成功 ({api_url})")
    except ImportError:
        print("[FAIL] openai パッケージがインストールされていません")
        print("       → uv pip install openai")
        return False
    except Exception as e:
        print(f"[FAIL] OpenAI クライアント作成エラー: {e}")
        return False

    # --- Step 2: WAV生成 ---
    print(f'[TTS CHECK] Step 2: WAVファイル生成 ("{text}")...')
    start_time = time.time()
    try:
        with client.audio.speech.with_streaming_response.create(
            model=model,
            response_format="wav",
            voice="",
            input=text,
        ) as response:
            response.stream_to_file(raw_wav)

        elapsed = time.time() - start_time

        if not os.path.exists(raw_wav):
            print("[FAIL] WAVファイルが生成されませんでした")
            return False

        file_size = os.path.getsize(raw_wav)
        if file_size < 100:
            print(f"[FAIL] WAVファイルが異常に小さい ({file_size} bytes)")
            return False

        # WAVヘッダー確認
        with open(raw_wav, "rb") as f:
            header = f.read(4)
            is_valid_wav = header == b"RIFF"

        if not is_valid_wav:
            print(f"[WARN] RIFFヘッダーがありません（生成ファイルが不正な可能性）")
        else:
            print(f"[OK] WAV生成完了 ({file_size} bytes, {elapsed:.2f}秒, 有効なRIFFヘッダー)")
    except Exception as e:
        print(f"[FAIL] WAV生成エラー: {e}")
        print("       → サービスの状態を確認:")
        print("         systemctl status llm-melotts")
        print("         systemctl status llm-openai-api")
        return False

    # --- Step 3: FFmpeg変換（オプション） ---
    playback_path = raw_wav
    if ffmpeg_convert:
        print("[TTS CHECK] Step 3: FFmpeg変換...")
        try:
            cmd = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", raw_wav,
                "-ar", "32000",
                "-ac", "2",
                "-sample_fmt", "s16",
                final_wav,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                print(f"[WARN] FFmpeg変換失敗: {result.stderr.strip()}")
                print("       → 変換なしで再生を試みます")
            else:
                final_size = os.path.getsize(final_wav)
                print(f"[OK] FFmpeg変換完了 ({final_size} bytes)")
                playback_path = final_wav
        except FileNotFoundError:
            print("[WARN] ffmpeg が見つかりません（変換なしで続行）")
        except Exception as e:
            print(f"[WARN] FFmpeg変換エラー: {e}（変換なしで続行）")
    else:
        print("[TTS CHECK] Step 3: FFmpeg変換スキップ")

    # --- Step 4: 再生（オプション） ---
    if play:
        print(f"[TTS CHECK] Step 4: tinyplay で再生...")
        try:
            cmd = ["tinyplay", f"-D{card}", f"-d{device}", playback_path]
            print(f"              cmd: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                print(f"[FAIL] tinyplay再生エラー: {result.stderr.strip()}")
                return False
            print("[OK] tinyplay 再生完了")
        except subprocess.TimeoutExpired:
            print("[WARN] tinyplay タイムアウト")
        except FileNotFoundError:
            print("[WARN] tinyplay が見つかりません")
        except Exception as e:
            print(f"[FAIL] tinyplay 再生エラー: {e}")
            return False
    else:
        print("[TTS CHECK] Step 4: 再生スキップ（--play で再生可能）")

    # --- Cleanup ---
    for path in [raw_wav, final_wav]:
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    print()
    print("[OK] TTS 音声合成チェック完了 ✓")
    return True


def main():
    parser = argparse.ArgumentParser(description="TTS音声合成チェック（デバイス上で実行）")
    parser.add_argument("--api-url", type=str, default="http://127.0.0.1:8000/v1",
                        help="OpenAI互換API URL (default: http://127.0.0.1:8000/v1)")
    parser.add_argument("--lang", type=str, default="ja", choices=["ja", "en", "zh"],
                        help="言語 (default: ja)")
    parser.add_argument("--model", type=str, default=None,
                        help="TTSモデル名（省略時は言語に応じて自動選択）")
    parser.add_argument("--text", type=str, default=None,
                        help="テストテキスト（省略時はデフォルト）")
    parser.add_argument("--play", action="store_true",
                        help="生成後にtinyplayで再生する")
    parser.add_argument("--card", type=int, default=0, help="ALSAカード番号 (default: 0)")
    parser.add_argument("--device", type=int, default=1, help="ALSAデバイス番号 (default: 1)")
    parser.add_argument("--no-ffmpeg", action="store_true",
                        help="FFmpeg変換をスキップ")
    args = parser.parse_args()

    ok = check_tts(
        api_url=args.api_url,
        lang=args.lang,
        model=args.model,
        text=args.text,
        play=args.play,
        card=args.card,
        device=args.device,
        ffmpeg_convert=not args.no_ffmpeg,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
