"""
bi_logger.py  —  BI Monitor ログ管理モジュール

ログ保存先:
  <プロジェクトルート>/logs/YYYY-MM-DD/
    01_system_log.txt / 01_system_error.txt
    02_led_log.txt    / 02_led_error.txt
    03_sound_log.txt  / 03_sound_error.txt
    04_llm_log.txt    / 04_llm_error.txt
    05_tts_log.txt    / 05_tts_error.txt
    99_run_history.txt / 99_run_error.txt

  99_run_history.txt には以下の2系統が混在する:
    - monitor/app.py から直接呼ばれるもの  (START / STOP / CHECK / TEST_IN)
    - バックグラウンドスクレイパーが tmux ログを解析して書くもの
      (STARTUP / SIGNAL_IN / GENERATED / TTS_START / SIGNAL_OUT / ERROR など)
"""

import os
import threading
from datetime import datetime

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_ROOT = os.path.join(_ROOT, "logs")

_lock = threading.Lock()

_FILES = {
    "system": ("01_system_log.txt",  "01_system_error.txt"),
    "led":    ("02_led_log.txt",     "02_led_error.txt"),
    "sound":  ("03_sound_log.txt",   "03_sound_error.txt"),
    "llm":    ("04_llm_log.txt",     "04_llm_error.txt"),
    "tts":    ("05_tts_log.txt",     "05_tts_error.txt"),
    "run":    ("99_run_history.txt", "99_run_error.txt"),
}

def _today_dir() -> str:
    d = os.path.join(LOG_ROOT, datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(d, exist_ok=True)
    return d

def _now_ts() -> str:
    return datetime.now().strftime("%H:%M:%S")

def _write(category: str, is_error: bool, line: str, ts: str = ""):
    files = _FILES.get(category)
    if files is None:
        return
    filename = files[1] if is_error else files[0]
    path = os.path.join(_today_dir(), filename)
    stamp = ts if ts else _now_ts()
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {line}\n")

def _node_tag(num: int) -> str:
    return f"NODE {num:03d} (10.0.0.{num})"

# ── バッチ見出し ──────────────────────────────────────────────────────
def log_batch(category: str, action: str, count: int):
    _write(category, False, f"===== BATCH {action:<14} {count} nodes =====")

# ── 01 SYSTEM ────────────────────────────────────────────────────────
def log_system(action: str, num: int, status: str, msg: str = ""):
    line = f"{_node_tag(num)}  {action:<10} {status.upper():<6} {msg}"
    _write("system", False, line)
    if status == "error":
        _write("system", True, line)

# ── 02 LED ───────────────────────────────────────────────────────────
def log_led(num: int, status: str, msg: str = ""):
    line = f"{_node_tag(num)}  {status.upper():<6} {msg}"
    _write("led", False, line)
    if status == "error":
        _write("led", True, line)

# ── 03 SOUND ─────────────────────────────────────────────────────────
def log_sound(num: int, status: str, msg: str = ""):
    line = f"{_node_tag(num)}  {status.upper():<6} {msg}"
    _write("sound", False, line)
    if status == "error":
        _write("sound", True, line)

# ── 04 LLM ───────────────────────────────────────────────────────────
def log_llm(action: str, num: int, status: str, msg: str = ""):
    line = f"{_node_tag(num)}  {action:<10} {status.upper():<6} {msg}"
    _write("llm", False, line)
    if status == "error":
        _write("llm", True, line)

# ── 05 TTS ───────────────────────────────────────────────────────────
def log_tts(action: str, num: int, status: str, msg: str = ""):
    line = f"{_node_tag(num)}  {action:<10} {status.upper():<6} {msg}"
    _write("tts", False, line)
    if status == "error":
        _write("tts", True, line)

# ── 99 RUN (monitor/app.py 直接呼び出し) ─────────────────────────────
def log_run_start(num: int, status: str, msg: str = ""):
    line = f"{_node_tag(num)}  START      {status.upper():<6} {msg}"
    _write("run", False, line)
    if status == "error":
        _write("run", True, line)

def log_run_stop(num: int, status: str, msg: str = ""):
    line = f"{_node_tag(num)}  STOP       {status.upper():<6} {msg}"
    _write("run", False, line)
    if status == "error":
        _write("run", True, line)

def log_run_check(num: int, status: str, msg: str = ""):
    line = f"{_node_tag(num)}  CHECK      {status.upper():<6} {msg}"
    _write("run", False, line)
    if status == "error":
        _write("run", True, line)

def log_run_test_input(num: int, text: str, ok: bool, stdout: str = "", stderr: str = ""):
    short = text[:50].replace("\n", " ")
    if ok:
        line = f"{_node_tag(num)}  TEST_IN    OK     text='{short}' -> '{stdout[:60]}'"
        _write("run", False, line)
    else:
        line = f"{_node_tag(num)}  TEST_IN    ERROR  text='{short}' -> ERR:'{stderr[:60]}'"
        _write("run", False, line)
        _write("run", True, line)

def log_run_error(num: int, phase: str, error: str, ts: str = ""):
    line = f"{_node_tag(num)}  ERROR [{phase.upper()}] {str(error)[:100].replace(chr(10),' ')}"
    _write("run", False, line, ts=ts)
    _write("run", True, line, ts=ts)

# ── 99 RUN (スクレイパーが tmux ログを解析して書くもの) ──────────────
def log_run_startup(num: int, ts: str = ""):
    _write("run", False, f"{_node_tag(num)}  STARTUP    BI cycle auto-started", ts=ts)

def log_run_signal_received(num: int, text: str, relay_count: int, ts: str = ""):
    short = text[:60].replace("\n", " ")
    _write("run", False,
           f"{_node_tag(num)}  SIGNAL_IN  relay={relay_count:<2}  text='{short}'", ts=ts)

def log_run_generated_raw(num: int, generated: str, ts: str = ""):
    short = generated[:60].replace("\n", " ")
    _write("run", False,
           f"{_node_tag(num)}  GENERATED  OK     out='{short}'", ts=ts)

def log_run_tts_start(num: int, ts: str = ""):
    _write("run", False, f"{_node_tag(num)}  TTS_PREP   WAV preparation started", ts=ts)

def log_run_tts_failed(num: int, ts: str = ""):
    line = f"{_node_tag(num)}  TTS_PREP   ERROR  WAV preparation failed"
    _write("run", False, line, ts=ts)
    _write("run", True, line, ts=ts)

def log_run_mixer_sent(num: int, text: str, ts: str = ""):
    short = text[:60].replace("\n", " ")
    _write("run", False,
           f"{_node_tag(num)}  SIGNAL_OUT MIXER  text='{short}'", ts=ts)

def log_run_relay_rejected(num: int, detail: str, ts: str = ""):
    _write("run", False,
           f"{_node_tag(num)}  RELAY_REJ  {detail[:80].replace(chr(10),' ')}", ts=ts)
