#!/usr/bin/env python3
import json
import os
import re
import time
import shutil
import hashlib
import subprocess
from pathlib import Path

# ===== 設定（必要なら環境変数で上書き）=====
OSC_JSON_DIR = Path(os.getenv("OSC_JSON_DIR", "/workspace/seed-vc/osc"))
DRIVE_PATH   = Path(os.getenv("DRIVE_PATH", "/workspace/seed-vc"))

TTS_DIR      = Path(os.getenv("TTS_DIR", str(DRIVE_PATH / "tts_out")))
OUT_DIR      = Path(os.getenv("OUT_DIR", str(DRIVE_PATH / "outputs")))

# drive_path="/workspace/seed-vc" なら "../nainiku.mp3" = "/workspace/nainiku.mp3" の想定
TARGET_AUDIO = Path(os.getenv("TARGET_AUDIO", str((DRIVE_PATH / "../nainiku.mp3").resolve())))
INFER_SCRIPT = Path(os.getenv("INFER_SCRIPT", str(DRIVE_PATH / "inference_v2.py")))

POLL_SEC     = float(os.getenv("POLL_SEC", "0.2"))

PROCESSED_DIR = OSC_JSON_DIR / "processed"
FAILED_DIR    = OSC_JSON_DIR / "failed"


def ensure_dirs():
    for d in [OSC_JSON_DIR, PROCESSED_DIR, FAILED_DIR, TTS_DIR, OUT_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def wait_file_stable(p: Path, checks: int = 6, interval: float = 0.2) -> bool:
    """scp転送中などの途中状態を避けるため、サイズが連続で変わらないことを確認"""
    last = -1
    stable = 0
    for _ in range(checks):
        try:
            s = p.stat().st_size
        except FileNotFoundError:
            return False
        if s == last:
            stable += 1
            if stable >= 3:
                return True
        else:
            stable = 0
            last = s
        time.sleep(interval)
    return True


def safe_basename(text: str, maxlen: int = 40) -> str:
    """
    「入力テキストの名前を使用」しつつ、ファイル名として危険な文字を潰して
    さらに衝突回避のためハッシュを付ける
    """
    t = text.strip()
    t = re.sub(r"\s+", "_", t)
    t = re.sub(r'[\\/:*?"<>|]+', "_", t)          # Windows系禁止文字も潰す
    t = re.sub(r"[\x00-\x1f]+", "_", t)           # 制御文字
    t = t[:maxlen] if t else "text"
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return f"{t}_{h}"


def run_melo(text: str, out_wav: Path):
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["melo", text, str(out_wav), "-l", "JP"]
    subprocess.run(cmd, check=True)


def run_infer(source_wav: Path):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cmd = [
        "python", str(INFER_SCRIPT),
        "--source", str(source_wav),
        "--target", str(TARGET_AUDIO),
        "--output", str(OUT_DIR),
        "--diffusion-steps", "30",
        "--length-adjust", "1.0",
        "--compile", "False",
        "--intelligibility-cfg-rate", "0.0",
        "--similarity-cfg-rate", "1.0",
        "--top-p", "1.0",
        "--temperature", "1.0",
        "--repetition-penalty", "1.0",
        "--convert-style", "False",
    ]
    # inference_v2.py が相対パス前提のことがあるので cwd を DRIVE_PATH に固定
    subprocess.run(cmd, check=True, cwd=str(DRIVE_PATH))

def extract_text(payload: dict) -> str:
    text = (payload.get("text") or "").strip()
    if not text:
        args = payload.get("args") or []
        text = " ".join(str(a) for a in args).strip()
    return text

def process_batch(json_paths: list[Path]):
    # scp転送中などの途中状態は除外
    stable_paths = [p for p in json_paths if wait_file_stable(p)]
    if not stable_paths:
        return

    texts: list[str] = []
    ok_paths: list[Path] = []
    bad_paths: list[Path] = []

    # 各jsonからtext抽出（壊れてる/空は failed に分離）
    for jp in stable_paths:
        try:
            payload = json.loads(jp.read_text(encoding="utf-8"))
            t = extract_text(payload)
            if not t:
                raise ValueError("No text in json")
            texts.append(t)
            ok_paths.append(jp)
        except Exception as e:
            print(f"[A] FAIL(json parse/text): {jp.name}  err={e}")
            bad_paths.append(jp)

    # 失敗分は先にfailedへ
    for jp in bad_paths:
        try:
            shutil.move(str(jp), str(FAILED_DIR / jp.name))
        except Exception:
            pass

    if not texts:
        return

    # ★ここが今回の変更点：全textを統合してmeloへ
    merged_text = "\n".join(texts)   # 区切りはお好みで：" " や "。" でもOK

    base = safe_basename(merged_text)
    tts_wav = TTS_DIR / f"{base}.wav"

    try:
        print(f"[A] melo(batch {len(texts)}): -> {tts_wav}")
        run_melo(merged_text, tts_wav)

        print(f"[A] infer: {tts_wav} -> {OUT_DIR} (target={TARGET_AUDIO})")
        run_infer(tts_wav)

        # 成功した分をprocessedへ（ok_pathsのみ）
        for jp in ok_paths:
            shutil.move(str(jp), str(PROCESSED_DIR / jp.name))
        print(f"[A] DONE(batch): {len(ok_paths)} files")

    except Exception as e:
        print(f"[A] FAIL(batch run): err={e}")
        # バッチ実行自体が失敗したら、ok_pathsもまとめてfailedへ
        for jp in ok_paths:
            try:
                shutil.move(str(jp), str(FAILED_DIR / jp.name))
            except Exception:
                pass


def process_one(json_path: Path):
    if not wait_file_stable(json_path):
        return

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        text = (payload.get("text") or "").strip()
        if not text:
            # argsから復元する保険
            args = payload.get("args") or []
            text = " ".join(str(a) for a in args).strip()

        if not text:
            raise ValueError("No text in json")

        base = safe_basename(text)
        tts_wav = TTS_DIR / f"{base}.wav"

        print(f"[A] melo: {text} -> {tts_wav}")
        run_melo(text, tts_wav)

        print(f"[A] infer: {tts_wav} -> {OUT_DIR} (target={TARGET_AUDIO})")
        run_infer(tts_wav)

        shutil.move(str(json_path), str(PROCESSED_DIR / json_path.name))
        print(f"[A] DONE: {json_path.name}")

    except Exception as e:
        print(f"[A] FAIL: {json_path.name}  err={e}")
        try:
            shutil.move(str(json_path), str(FAILED_DIR / json_path.name))
        except Exception:
            pass


def main():
    ensure_dirs()
    print(f"[A] watch json: {OSC_JSON_DIR}")
    print(f"[A] drive_path: {DRIVE_PATH}")
    print(f"[A] target_audio: {TARGET_AUDIO}")
    print(f"[A] outputs: {OUT_DIR}")

    while True:
        batch = sorted(OSC_JSON_DIR.glob("*.json"))
        if batch:
            process_batch(batch)
        time.sleep(POLL_SEC)

    # while True:
    #     for jp in sorted(OSC_JSON_DIR.glob("*.json")):
    #         process_one(jp)
    #     time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
