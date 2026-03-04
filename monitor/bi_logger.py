"""
bi_logger.py  —  BI Monitor ログ管理モジュール

ログ保存先:
  <プロジェクトルート>/logs/YYYY-MM-DD/
    01_system_log.txt      # 01 SYSTEM 動作チェックログ（複数回分、時刻付き）
    01_system_error.txt    # 01 SYSTEM エラー
    02_led_log.txt         # 02 LED チェックログ
    02_led_error.txt       # 02 LED エラー
    03_sound_log.txt       # 03 SOUND チェックログ
    03_sound_error.txt     # 03 SOUND エラー
    04_llm_log.txt         # 04 LLM チェックログ
    04_llm_error.txt       # 04 LLM エラー
    05_tts_log.txt         # 05 TTS チェックログ
    05_tts_error.txt       # 05 TTS エラー
    99_run_history.txt     # 99 RUN 重要抜粋（起動・信号受信・生成・再生・送信）
    99_run_error.txt       # 99 RUN エラー
"""

import os
import threading
from datetime import datetime

# プロジェクトルート = monitor/ の親ディレクトリ
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_ROOT = os.path.join(_ROOT, "logs")

_lock = threading.Lock()

# カテゴリ -> (通常ログファイル名, エラーログファイル名)
_FILES = {
    "system": ("01_system_log.txt",  "01_system_error.txt"),
    "led":    ("02_led_log.txt",     "02_led_error.txt"),
    "sound":  ("03_sound_log.txt",   "03_sound_error.txt"),
    "llm":    ("04_llm_log.txt",     "04_llm_error.txt"),
    "tts":    ("05_tts_log.txt",     "05_tts_error.txt"),
    "run":    ("99_run_history.txt", "99_run_error.txt"),
}


# ──────────────────────────────────────────────
#  内部ユーティリティ
# ──────────────────────────────────────────────

def _today_dir() -> str:
    """今日の日付フォルダを返す（なければ作成）"""
    d = os.path.join(LOG_ROOT, datetime.now().strftime("%Y-%m-%d"))
    os.makedirs(d, exist_ok=True)
    return d


def _write(category: str, is_error: bool, line: str):
    """1行をログファイルに追記する（スレッドセーフ）"""
    files = _FILES.get(category)
    if files is None:
        return
    filename = files[1] if is_error else files[0]
    path = os.path.join(_today_dir(), filename)
    ts = datetime.now().strftime("%H:%M:%S")
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")


def _node_tag(num: int) -> str:
    return f"NODE {num:03d} (10.0.0.{num})"


# ──────────────────────────────────────────────
#  バッチ操作の見出し行
# ──────────────────────────────────────────────

def log_batch(category: str, action: str, count: int):
    """
    例: [10:31:00] ===== BATCH ping  100 nodes =====
    """
    line = f"===== BATCH {action:<12} {count} nodes ====="
    _write(category, False, line)


# ──────────────────────────────────────────────
#  01 SYSTEM
# ──────────────────────────────────────────────

def log_system(action: str, num: int, status: str, msg: str = ""):
    """
    SYSTEM チェック（ping / inet / gitpull / reboot）の結果を記録。
    status == "error" の場合はエラーファイルにも書く。

    例（通常）: NODE 001 (10.0.0.1)  ping       OK    1.2ms
    例（エラー）: NODE 003 (10.0.0.3)  ping       ERROR offline
    """
    status_up = status.upper()
    line = f"{_node_tag(num)}  {action:<10} {status_up:<6} {msg}"
    is_err = (status == "error")
    _write("system", False, line)          # 通常ログには常に書く
    if is_err:
        _write("system", True, line)       # エラーファイルにも書く


# ──────────────────────────────────────────────
#  02 LED
# ──────────────────────────────────────────────

def log_led(num: int, status: str, msg: str = ""):
    """
    例: NODE 005 (10.0.0.5)  OK    done / off
    """
    status_up = status.upper()
    line = f"{_node_tag(num)}  {status_up:<6} {msg}"
    is_err = (status == "error")
    _write("led", False, line)
    if is_err:
        _write("led", True, line)


# ──────────────────────────────────────────────
#  03 SOUND
# ──────────────────────────────────────────────

def log_sound(num: int, status: str, msg: str = ""):
    """
    例: NODE 012 (10.0.0.12)  OK    played
    """
    status_up = status.upper()
    line = f"{_node_tag(num)}  {status_up:<6} {msg}"
    is_err = (status == "error")
    _write("sound", False, line)
    if is_err:
        _write("sound", True, line)


# ──────────────────────────────────────────────
#  04 LLM
# ──────────────────────────────────────────────

def log_llm(action: str, num: int, status: str, msg: str = ""):
    """
    action: start / stop / check
    例: NODE 007 (10.0.0.7)  start      OK    tmux started
    """
    status_up = status.upper()
    line = f"{_node_tag(num)}  {action:<10} {status_up:<6} {msg}"
    is_err = (status == "error")
    _write("llm", False, line)
    if is_err:
        _write("llm", True, line)


# ──────────────────────────────────────────────
#  05 TTS
# ──────────────────────────────────────────────

def log_tts(action: str, num: int, status: str, msg: str = ""):
    """
    action: start / stop / check
    例: NODE 050 (10.0.0.50)  check      OK    running
    """
    status_up = status.upper()
    line = f"{_node_tag(num)}  {action:<10} {status_up:<6} {msg}"
    is_err = (status == "error")
    _write("tts", False, line)
    if is_err:
        _write("tts", True, line)


# ──────────────────────────────────────────────
#  99 RUN — 重要イベント（抜粋）
# ──────────────────────────────────────────────

def log_run_start(num: int, status: str, msg: str = ""):
    """
    tmux セッション起動。
    例: NODE 001 (10.0.0.1)  START      OK    tmux started
    """
    status_up = status.upper()
    line = f"{_node_tag(num)}  START      {status_up:<6} {msg}"
    is_err = (status == "error")
    _write("run", False, line)
    if is_err:
        _write("run", True, line)


def log_run_stop(num: int, status: str, msg: str = ""):
    """
    例: NODE 001 (10.0.0.1)  STOP       OK    stopped
    """
    status_up = status.upper()
    line = f"{_node_tag(num)}  STOP       {status_up:<6} {msg}"
    is_err = (status == "error")
    _write("run", False, line)
    if is_err:
        _write("run", True, line)


def log_run_check(num: int, status: str, msg: str = ""):
    """
    例: NODE 001 (10.0.0.1)  CHECK      OK    running
    """
    status_up = status.upper()
    line = f"{_node_tag(num)}  CHECK      {status_up:<6} {msg}"
    is_err = (status == "error")
    _write("run", False, line)
    if is_err:
        _write("run", True, line)


def log_run_test_input(num: int, text: str, ok: bool, stdout: str = "", stderr: str = ""):
    """
    テスト信号の送信結果。
    例（成功）: NODE 042 (10.0.0.42)  TEST_IN    OK    text='こんにちは' -> response='ok'
    例（失敗）: NODE 042 (10.0.0.42)  TEST_IN    ERROR text='こんにちは' -> stderr='timeout'
    """
    short_text = text[:50].replace("\n", " ")
    if ok:
        detail = f"text='{short_text}' -> response='{stdout[:60]}'"
        line = f"{_node_tag(num)}  TEST_IN    OK     {detail}"
        _write("run", False, line)
    else:
        detail = f"text='{short_text}' -> stderr='{stderr[:60]}'"
        line = f"{_node_tag(num)}  TEST_IN    ERROR  {detail}"
        _write("run", False, line)
        _write("run", True, line)


# ──────────────────────────────────────────────
#  bi/controller.py から呼ばれる RUN ログ
#  （m5stack 側の main.py が Ubuntu 上で実行される場合）
# ──────────────────────────────────────────────

def log_run_signal_received(num: int, text: str, relay_count: int):
    """
    OSC 信号 /bi/input を受信。
    例: NODE 001 (10.0.0.1)  SIGNAL_IN  relay=2  text='こんにちは...'
    """
    short = text[:60].replace("\n", " ")
    line = f"{_node_tag(num)}  SIGNAL_IN  relay={relay_count:<2}  text='{short}'"
    _write("run", False, line)


def log_run_generated(num: int, input_text: str, generated: str, success: bool):
    """
    LLM テキスト生成の結果。
    例（成功）: NODE 001 (10.0.0.1)  GENERATED  OK    input='...' -> out='...'
    例（失敗）: NODE 001 (10.0.0.1)  GENERATED  ERROR input='...'
    """
    short_in  = input_text[:40].replace("\n", " ")
    short_out = generated[:40].replace("\n", " ")
    if success:
        line = f"{_node_tag(num)}  GENERATED  OK     input='{short_in}' -> out='{short_out}'"
        _write("run", False, line)
    else:
        line = f"{_node_tag(num)}  GENERATED  ERROR  input='{short_in}'"
        _write("run", False, line)
        _write("run", True, line)


def log_run_playback(num: int, tts_text: str, success: bool):
    """
    TTS 再生の結果。
    例（成功）: NODE 001 (10.0.0.1)  PLAYBACK   OK    text='...'
    例（失敗）: NODE 001 (10.0.0.1)  PLAYBACK   ERROR text='...'
    """
    short = tts_text[:60].replace("\n", " ")
    if success:
        line = f"{_node_tag(num)}  PLAYBACK   OK     text='{short}'"
        _write("run", False, line)
    else:
        line = f"{_node_tag(num)}  PLAYBACK   ERROR  text='{short}'"
        _write("run", False, line)
        _write("run", True, line)


def log_run_signal_sent(num: int, target_count: int, text: str, relay_count: int):
    """
    OSC 信号 /bi/input を隣接ノードへ送信。
    例: NODE 001 (10.0.0.1)  SIGNAL_OUT targets=3  relay=3  text='...'
    """
    short = text[:60].replace("\n", " ")
    line = f"{_node_tag(num)}  SIGNAL_OUT targets={target_count:<3} relay={relay_count:<2}  text='{short}'"
    _write("run", False, line)


def log_run_error(num: int, phase: str, error: str):
    """
    RUN サイクル中の汎用エラー。
    例: NODE 001 (10.0.0.1)  ERROR [GENERATING] Connection refused
    """
    short_err = str(error)[:120].replace("\n", " ")
    line = f"{_node_tag(num)}  ERROR [{phase.upper()}] {short_err}"
    _write("run", False, line)
    _write("run", True, line)
