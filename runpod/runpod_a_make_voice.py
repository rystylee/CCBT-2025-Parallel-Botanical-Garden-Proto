#!/usr/bin/env python3
"""RunPod ワーカー: MeloTTS → Seed-VC 音声変換パイプライン

RunPod 上で動作。osc/ ディレクトリに到着した JSON ファイルを監視し、
テキスト → MeloTTS(WAV生成) → Seed-VC(声質変換) のパイプラインを実行する。

パスは runpod_config.json の "runpod" セクションから読み込み。
環境変数が設定されていればそちらを優先する。

使い方:
    python3 runpod_a_make_voice.py
    python3 runpod_a_make_voice.py --config /path/to/runpod_config.json
    BATCH_MODE=0 python3 runpod_a_make_voice.py   # 1件ずつ処理
"""

import argparse
import json
import os
import re
import sys
import time
import shutil
import hashlib
import subprocess
from pathlib import Path
from datetime import datetime


# ===== 設定読み込み =====

def load_config(config_path: str | None = None) -> dict:
    """runpod_config.json を読み込む。見つからなければ空dictを返す。"""
    candidates = []
    if config_path:
        candidates.append(Path(config_path))
    # スクリプトと同じディレクトリ → 1つ上のディレクトリ
    candidates += [
        Path(__file__).parent / "runpod_config.json",
        Path(__file__).parent.parent / "runpod_config.json",
    ]
    for p in candidates:
        if p.exists():
            log(f"config読み込み: {p}")
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    log("⚠️  runpod_config.json が見つかりません (デフォルト値を使用)")
    return {}


def resolve_paths(cfg: dict) -> dict:
    """config の runpod セクション + 環境変数 → パス辞書を返す。
    優先順位: 環境変数 > config > ハードコードデフォルト
    """
    rp = cfg.get("runpod", {})

    def pick(env_key: str, config_key: str, default: str) -> Path:
        return Path(os.getenv(env_key) or rp.get(config_key) or default)

    seed_vc_dir = pick("DRIVE_PATH", "seed_vc_dir", "/workspace/dev/seed-vc")

    return {
        "osc_json_dir": pick("OSC_JSON_DIR", "osc_json_dir", str(seed_vc_dir / "osc")),
        "seed_vc_dir":  seed_vc_dir,
        "tts_dir":      pick("TTS_DIR", "tts_out_dir", str(seed_vc_dir / "tts_out")),
        "out_dir":      pick("OUT_DIR", "vc_out_dir", str(seed_vc_dir / "outputs")),
        "target_audio": pick("TARGET_AUDIO", "target_audio",
                             "/workspace/dev/CCBT-2025-Parallel-Botanical-Garden-Proto/audio/nainiku.mp3"),
        "infer_script": pick("INFER_SCRIPT", "",  str(seed_vc_dir / "inference_v2.py")),
        "melo_bin":     pick("MELO_BIN", "melo_bin", "melo"),
    }


# ===== グローバル (main で初期化) =====

OSC_JSON_DIR: Path
DRIVE_PATH: Path
TTS_DIR: Path
OUT_DIR: Path
TARGET_AUDIO: Path
INFER_SCRIPT: Path
MELO_BIN: Path
PROCESSED_DIR: Path
FAILED_DIR: Path

POLL_SEC        = float(os.getenv("POLL_SEC", "0.2"))
BATCH_MODE      = os.getenv("BATCH_MODE", "1") == "1"
MAX_TEXT_CHARS   = int(os.getenv("MAX_TEXT_CHARS", "500"))


# ===== ユーティリティ =====

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def ensure_dirs():
    for d in [OSC_JSON_DIR, PROCESSED_DIR, FAILED_DIR, TTS_DIR, OUT_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def wait_file_stable(p: Path, checks: int = 6, interval: float = 0.2) -> bool:
    """SCP転送中の途中ファイルを回避: サイズが安定するまで待つ"""
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


# def safe_basename(text: str, maxlen: int = 40) -> str:
#     """テキストからファイル名安全なベース名を生成"""
#     t = text.strip()
#     t = re.sub(r"\s+", "_", t)
#     t = re.sub(r'[\\/:*?"<>|]+', "_", t)
#     t = re.sub(r"[\x00-\x1f]+", "_", t)
#     t = t[:maxlen] if t else "text"
#     h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
#     return f"{t}_{h}"

def safe_basename(text: str, maxlen: int = 40) -> str:
    """日時ベースのファイル名を生成"""
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

def load_ng_words_config() -> dict:
    """ngwords.json を探して読み込む。"""
    candidates = [
        Path(__file__).parent / "ngwords.json",
        Path(__file__).parent.parent / "config" / "ngwords.json",
        Path(__file__).parent / "config" / "ngwords.json",
    ]
    for p in candidates:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    return {}

def cleanup_ng_words(text: str) -> str:
    """ngwords.json に基づいてテキストをクリーンアップする。"""
    data = load_ng_words_config()

    # 0) 改行フラット化
    text = text.replace("\\n", "\n").replace("\r", "")

    # 1) drop_line_patterns: マッチ行を丸ごと除去
    drop_patterns = data.get("drop_line_patterns", [])
    if drop_patterns:
        lines = text.splitlines()
        kept = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if any(re.search(pat, stripped) for pat in drop_patterns):
                continue
            kept.append(stripped)
        text = "".join(kept)

    # 1.5) meta_instruction_patterns: メタ指示/質問文を含むフレーズを除去
    meta_patterns = data.get("meta_instruction_patterns", [])
    if meta_patterns and text:
        # 句点・疑問符で文を分割し、メタ指示パターンを含む文を除去
        # (句読点除去(step 5)の前に実行する必要がある)
        sentences = re.split(r"(?<=[。？！\?!])", text)
        kept_sentences = []
        for sent in sentences:
            s = sent.strip()
            if not s:
                continue
            if any(re.search(pat, s) for pat in meta_patterns):
                continue
            kept_sentences.append(s)
        text = "".join(kept_sentences)

    # 2) preamble_keywords: 先頭の定型句を繰り返し除去
    preamble_kw = data.get("preamble_keywords", [])
    changed = True
    while changed:
        changed = False
        for kw in preamble_kw:
            if text.startswith(kw):
                text = text[len(kw):]
                changed = True

    # 3) strip_prefixes: 先頭プレフィックスを正規表現で除去
    for pat in data.get("strip_prefixes", []):
        text = re.sub(r"^" + pat, "", text)

    # 4) strip_symbols: Markdown残骸などを全体から除去
    for sym in data.get("strip_symbols", []):
        text = text.replace(sym, "")

    # 5) strip_punctuation: 句読点除去
    for p in data.get("strip_punctuation", []):
        text = text.replace(p, "")

    # 6) 空白正規化
    text = re.sub(r"\s+", " ", text).strip()
    return text

def extract_text(payload: dict) -> str:
    text = (payload.get("text") or "").strip()
    if not text:
        args = payload.get("args") or []
        text = " ".join(str(a) for a in args).strip()

    if text:
        original = text
        text = cleanup_ng_words(text)
        if text != original:
            log(f"NGワード除去: '{original[:60]}' → '{text[:60]}'")

    return text

# ===== パイプライン =====

def run_melo(text: str, out_wav: Path):
    """MeloTTS でテキスト→WAV生成"""
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(MELO_BIN), text, str(out_wav), "-l", "JP"]
    log(f"MeloTTS: {text[:60]}... → {out_wav.name}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log(f"MeloTTS stderr:\n{result.stderr}")
        raise RuntimeError(f"MeloTTS failed (returncode={result.returncode})")
    if not out_wav.exists() or out_wav.stat().st_size == 0:
        raise RuntimeError(f"MeloTTS produced empty/no file: {out_wav}")


def run_infer(source_wav: Path):
    """Seed-VC で声質変換"""
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
    log(f"Seed-VC: {source_wav.name} → {OUT_DIR}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(DRIVE_PATH))
    if result.returncode != 0:
        log(f"Seed-VC stderr:\n{result.stderr}")
        raise RuntimeError(f"Seed-VC failed (returncode={result.returncode})")


def move_safe(src: Path, dst_dir: Path):
    """ファイルを安全に移動 (同名ファイル存在時はタイムスタンプ付加)"""
    dst = dst_dir / src.name
    if dst.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = dst_dir / f"{src.stem}_{ts}{src.suffix}"
    shutil.move(str(src), str(dst))


# ===== 処理ループ =====

def process_batch(json_paths: list[Path]):
    """複数JSONをまとめて処理"""
    stable_paths = [p for p in json_paths if wait_file_stable(p)]
    if not stable_paths:
        return

    texts: list[str] = []
    ok_paths: list[Path] = []
    bad_paths: list[Path] = []
    total_chars = 0

    for jp in stable_paths:
        try:
            payload = json.loads(jp.read_text(encoding="utf-8"))
            t = extract_text(payload)
            if not t:
                raise ValueError("空テキスト")
            # 文字数上限: 超えたらここまでで処理し、残りは次回ポーリングへ
            if total_chars + len(t) > MAX_TEXT_CHARS and texts:
                log(f"[RunPod] バッチ上限到達: {total_chars}文字 (MAX={MAX_TEXT_CHARS}), 残り{len(stable_paths) - len(ok_paths) - len(bad_paths)}件は次回")
                break
            texts.append(t)
            ok_paths.append(jp)
            total_chars += len(t)
        except Exception as e:
            log(f"❌ JSON解析失敗: {jp.name} → {e}")
            bad_paths.append(jp)

    for jp in bad_paths:
        try:
            move_safe(jp, FAILED_DIR)
        except Exception:
            pass

    if not texts:
        return

    merged_text = "\n".join(texts)
    base = safe_basename(merged_text)
    tts_wav = TTS_DIR / f"{base}.wav"

    try:
        t0 = time.time()
        run_melo(merged_text, tts_wav)
        t1 = time.time()
        log(f"MeloTTS完了 ({t1 - t0:.1f}s)")

        run_infer(tts_wav)
        t2 = time.time()
        log(f"Seed-VC完了 ({t2 - t1:.1f}s)")

        for jp in ok_paths:
            move_safe(jp, PROCESSED_DIR)

        log(f"✅ バッチ完了: {len(ok_paths)}件 (合計 {t2 - t0:.1f}s)")

    except Exception as e:
        log(f"❌ パイプライン失敗: {e}")
        for jp in ok_paths:
            try:
                move_safe(jp, FAILED_DIR)
            except Exception:
                pass

    # TTS中間ファイル削除
    if tts_wav.exists():
        try:
            tts_wav.unlink()
        except Exception:
            pass


def process_one(json_path: Path):
    """1件ずつ処理"""
    if not wait_file_stable(json_path):
        return

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        text = extract_text(payload)
        if not text:
            raise ValueError("空テキスト")

        base = safe_basename(text)
        tts_wav = TTS_DIR / f"{base}.wav"

        t0 = time.time()
        run_melo(text, tts_wav)
        run_infer(tts_wav)
        elapsed = time.time() - t0

        move_safe(json_path, PROCESSED_DIR)
        log(f"✅ 完了: {json_path.name} ({elapsed:.1f}s)")

        if tts_wav.exists():
            tts_wav.unlink()

    except Exception as e:
        log(f"❌ 失敗: {json_path.name} → {e}")
        try:
            move_safe(json_path, FAILED_DIR)
        except Exception:
            pass


def verify_prerequisites():
    """起動前チェック"""
    errors = []

    r = subprocess.run([str(MELO_BIN), "--help"], capture_output=True, text=True)
    if r.returncode != 0 and not MELO_BIN.exists():
        errors.append(f"melo が見つかりません: {MELO_BIN}")

    if not INFER_SCRIPT.exists():
        errors.append(f"inference_v2.py が見つかりません: {INFER_SCRIPT}")

    if not TARGET_AUDIO.exists():
        errors.append(f"ターゲット音声が見つかりません: {TARGET_AUDIO}")

    if errors:
        log("=" * 50)
        log("⚠️  起動前チェック失敗:")
        for e in errors:
            log(f"  - {e}")
        log("=" * 50)
        return False

    return True


# ===== メイン =====

def main():
    global OSC_JSON_DIR, DRIVE_PATH, TTS_DIR, OUT_DIR
    global TARGET_AUDIO, INFER_SCRIPT, MELO_BIN, PROCESSED_DIR, FAILED_DIR

    parser = argparse.ArgumentParser(description="RunPod Voice Worker")
    parser.add_argument("--config", default=None, help="runpod_config.json のパス")
    args = parser.parse_args()

    # config 読み込み → パス解決
    cfg = load_config(args.config)
    paths = resolve_paths(cfg)

    OSC_JSON_DIR  = paths["osc_json_dir"]
    DRIVE_PATH    = paths["seed_vc_dir"]
    TTS_DIR       = paths["tts_dir"]
    OUT_DIR       = paths["out_dir"]
    TARGET_AUDIO  = paths["target_audio"]
    INFER_SCRIPT  = paths["infer_script"]
    MELO_BIN      = paths["melo_bin"]
    PROCESSED_DIR = OSC_JSON_DIR / "processed"
    FAILED_DIR    = OSC_JSON_DIR / "failed"

    ensure_dirs()

    log("=" * 50)
    log("RunPod Voice Worker 起動")
    log(f"  JSON監視:  {OSC_JSON_DIR}")
    log(f"  Seed-VC:   {DRIVE_PATH}")
    log(f"  TTS出力:   {TTS_DIR}")
    log(f"  VC出力:    {OUT_DIR}")
    log(f"  ターゲット: {TARGET_AUDIO}")
    log(f"  MeloTTS:   {MELO_BIN}")
    log(f"  推論:      {INFER_SCRIPT}")
    log(f"  モード:    {'バッチ' if BATCH_MODE else '1件ずつ'}")
    log(f"  バッチ上限: {MAX_TEXT_CHARS}文字")
    log(f"  ポーリング: {POLL_SEC}s")
    log("=" * 50)

    if not verify_prerequisites():
        log("前提条件を満たしていません。")
        sys.exit(1)

    log("ファイル監視開始...")

    while True:
        try:
            batch = sorted(OSC_JSON_DIR.glob("*.json"))
            if batch:
                if BATCH_MODE:
                    process_batch(batch)
                else:
                    for jp in batch:
                        process_one(jp)
        except KeyboardInterrupt:
            log("中断 (Ctrl+C)")
            break
        except Exception as e:
            log(f"❌ 予期しないエラー: {e}")

        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
