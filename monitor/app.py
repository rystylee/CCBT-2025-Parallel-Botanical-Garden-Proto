"""
BI MONITOR - 8 pages
  /          -> Page 1: SYSTEM (ping + inet + git pull + reboot)
  /led       -> Page 2: LED
  /sound     -> Page 3: Sound
  /llm       -> Page 4: LLM
  /tts       -> Page 5: TTS
  /run       -> Page 6: Run Scripts (tmux)
  /terminal  -> Page 7: Interactive SSH Terminal
  /broadcast -> Page 8: Command Broadcast
"""
from flask import Flask, jsonify, request, render_template_string
from flask_socketio import SocketIO, emit
from pythonosc import udp_client
import paramiko
import threading, time, subprocess, getpass
import os
import bi_logger

app = Flask(__name__)
app.config["SECRET_KEY"] = os.urandom(24).hex()
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
NODE_PREFIX = "10.0.0"
NODE_COUNT  = 100
OSC_PORT    = 9000
SSH_USER    = "root"
GIT_DIR     = "/root/dev/CCBT-2025-Parallel-Botanical-Garden-Proto"
SOUND_CMD   = "tinyplay -D0 -d1 /usr/local/m5stack/logo.wav"
LED_SERVER_SESSION = "bi_led_srv"
LED_SERVER_CMD = f"cd {GIT_DIR} && uv run python pca9685_osc_led_server.py --port {OSC_PORT}"
LED_STEPS   = 40
LED_UP_SEC  = 2.0
LED_DN_SEC  = 2.0
SSH_PASS = getpass.getpass("SSH Password: ")

# RUN ログファイルパス（各ノード上）
RUN_LOG_FILE = "/tmp/bi_run.log"

TMUX_CONF = {
    "run": {
        "session": "bi_main",
        # 2>&1 | tee でファイルにも書き出す → tmux スクロールバック依存を回避
        # tee -a で追記モード（再起動時も続きから読める）
        "cmd": f"cd {GIT_DIR} && git stash; git pull; uv run python main.py 2>&1 | tee -a {RUN_LOG_FILE}",
    },
    "llm": {
        "session": "bi_llm",
        "cmd": f"cd {GIT_DIR} && git stash; git pull; chmod +x scripts/check_llm.py && ./scripts/check_llm.py",
    },
    "tts": {
        "session": "bi_tts",
        "cmd": f"cd {GIT_DIR} && git stash; git pull; chmod +x scripts/check_tts.py && ./scripts/check_tts.py",
    },
}
SEND_SCRIPT = "/home/yuma/dev/CCBT-2025-Parallel-Botanical-Garden-Proto/scripts/send_bi_input.py"

PAGES = ["system", "led", "sound", "llm", "tts", "run"]
jobs = {p: {n: {"status":"idle","msg":""} for n in range(1,NODE_COUNT+1)} for p in PAGES}
job_locks = {p: {n: threading.Lock() for n in range(1,NODE_COUNT+1)} for p in PAGES}
script_logs = {p: {n: "" for n in range(1, NODE_COUNT+1)} for p in ["run", "llm", "tts"]}
script_logs_lock = threading.Lock()

SSH_SEMAPHORE = threading.Semaphore(20)

# ── Interactive SSH Session Manager (paramiko) ────────────────────────
_ssh_sessions = {}   # sid -> {client, channel, device_id, active}
_ssh_lock = threading.Lock()

def _ssh_open_interactive(sid, device_id):
    """Open an interactive SSH shell session for WebSocket terminal."""
    ip = node_ip(device_id)
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, port=22, username=SSH_USER, password=SSH_PASS, timeout=10)
        channel = client.invoke_shell(term="xterm-256color", width=120, height=40)
        channel.settimeout(0.1)
        with _ssh_lock:
            _ssh_close_interactive(sid)
            _ssh_sessions[sid] = {"client": client, "channel": channel, "device_id": device_id, "active": True}
        return True
    except Exception as e:
        return str(e)

def _ssh_close_interactive(sid):
    """Close an interactive SSH session."""
    session = _ssh_sessions.pop(sid, None)
    if session:
        session["active"] = False
        try: session["channel"].close()
        except: pass
        try: session["client"].close()
        except: pass

# ── RUN ログスクレイパー ──────────────────────────────────────────────
import re as _re

# ANSI エスケープシーケンスを除去するパターン
# loguru はターミナルに色付きで出力するため tmux capture-pane にカラーコードが混入する
_ANSI_RE = _re.compile(r'\x1b\[[0-9;]*[mGKHF]|\x1b\(B|\x1b=|\x1b>')

# ノードごとに「すでにログ済みの行フィンガープリント」を保持（重複防止）
_run_scrape_seen: dict = {n: set() for n in range(1, NODE_COUNT + 1)}
_run_scrape_lock = threading.Lock()


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _parse_loguru(raw_line: str):
    """loguru 出力行をパース → (timestamp_str, level, message) or None

    ANSI カラーコードを除去してからパースする。
    形式: "2025-06-15 18:19:01.234 | INFO     | module:func:line - message"
    """
    line = _strip_ansi(raw_line)
    try:
        parts = line.split(" | ", 2)
        if len(parts) < 3:
            return None
        ts    = parts[0].strip()
        level = parts[1].strip()
        rest  = parts[2]
        msg   = rest.split(" - ", 1)[1] if " - " in rest else rest
        # タイムスタンプの基本チェック（数字で始まる年を期待）
        if not ts[:4].isdigit():
            return None
        return ts, level, msg.strip()
    except Exception:
        return None


def _dispatch_scrape_event(num: int, ts: str, level: str, msg: str):
    """パース済みの loguru 行を解釈して bi_logger に書き込む"""
    hh = ts[11:19] if len(ts) >= 19 else ts   # "HH:MM:SS" 部分

    if m := _re.search(r"Added input: '(.{0,80})' relay_count=(\d+)->(\d+)", msg):
        bi_logger.log_run_signal_received(num, m.group(1), int(m.group(2)), ts=hh)

    elif m := _re.search(r"Generated text: (.+)", msg):
        bi_logger.log_run_generated_raw(num, m.group(1).strip(), ts=hh)

    elif "Preparing WAV file" in msg:
        bi_logger.log_run_tts_start(num, ts=hh)

    elif "WAV preparation failed" in msg:
        bi_logger.log_run_tts_failed(num, ts=hh)

    elif m := _re.search(r"Sent to Mixer PC: (.+)", msg):
        bi_logger.log_run_mixer_sent(num, m.group(1).strip(), ts=hh)

    elif m := _re.search(r"Error sending to targets: (.+)", msg):
        bi_logger.log_run_error(num, "SIGNAL_OUT", m.group(1), ts=hh)

    elif m := _re.search(r"Error in generation: (.+)", msg):
        bi_logger.log_run_error(num, "GENERATING", m.group(1), ts=hh)

    elif m := _re.search(r"Error in TTS playback: (.+)", msg):
        bi_logger.log_run_error(num, "PLAYBACK", m.group(1), ts=hh)

    elif m := _re.search(r"Error in BI cycle: (.+)", msg):
        bi_logger.log_run_error(num, "CYCLE", m.group(1), ts=hh)

    elif m := _re.search(r"Rejected data exceeding relay limit: (.+)", msg):
        bi_logger.log_run_relay_rejected(num, m.group(1), ts=hh)

    elif "Auto-starting BI cycle" in msg or "Starting BI system" in msg:
        bi_logger.log_run_startup(num, ts=hh)


def _scrape_node_run_log(num: int):
    """1ノードの RUN ログファイルを読んで新行だけ bi_logger に書き込む。
    tee で書かれた /tmp/bi_run.log を tail で読む。
    ファイル経由なので tmux スクロールバック問題・ANSI コード問題を回避できる。
    loguru は TTY でないと判断して ANSI カラーコードを出力しないため _strip_ansi 不要。
    """
    try:
        # 直近800行を取得（ファイルなので行数制限なし・確実に残る）
        code, out, _ = ssh_run(
            node_ip(num),
            f"tail -n 800 {RUN_LOG_FILE} 2>/dev/null",
            timeout=12,
        )
        if code != 0 or not out.strip():
            return
        new_events = []
        with _run_scrape_lock:
            seen = _run_scrape_seen[num]
            for line in out.splitlines():
                parsed = _parse_loguru(line)
                if not parsed:
                    continue
                ts, level, msg = parsed
                fp = (ts[:19], msg[:80])
                if fp in seen:
                    continue
                seen.add(fp)
                new_events.append((ts, level, msg))
            if len(seen) > 5000:
                _run_scrape_seen[num] = set(list(seen)[-2500:])
        for ts, level, msg in new_events:
            _dispatch_scrape_event(num, ts, level, msg)
    except Exception:
        pass


def _run_scraper_loop():
    """バックグラウンドスレッド: 30秒ごとに稼働中の RUN ノードをスクレイプ"""
    time.sleep(15)           # アプリ起動直後は待機
    while True:
        active = [n for n in range(1, NODE_COUNT + 1)
                  if jobs["run"][n]["status"] == "ok"]
        for num in active:
            threading.Thread(
                target=_scrape_node_run_log, args=(num,), daemon=True
            ).start()
            time.sleep(0.15)  # SSH 接続を少しずつ開く
        time.sleep(30)

def set_job(page, num, status, msg=""):
    jobs[page][num] = {"status": status, "msg": msg}
def is_running(page, num):
    return jobs[page][num]["status"] == "running"
def node_ip(num):
    return f"{NODE_PREFIX}.{num}"
def ping_ip(ip):
    try:
        r = subprocess.run(["ping","-c","1","-W","1",ip], capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            for line in r.stdout.split("\n"):
                if "time=" in line:
                    return True, f"{line.split('time=')[1].split(' ')[0]}ms"
            return True, "ok"
        return False, "offline"
    except:
        return False, "error"

SSH_CONTROL_DIR = "/tmp/bi_ssh_ctrl"
os.makedirs(SSH_CONTROL_DIR, exist_ok=True)

def ssh_run(ip, cmd, timeout=15):
    SSH_SEMAPHORE.acquire()
    try:
        ctrl = f"{SSH_CONTROL_DIR}/%r@%h:%p"
        r = subprocess.run([
            "sshpass", "-p", SSH_PASS, "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=5",
            "-o", f"ControlPath={ctrl}",
            "-o", "ControlMaster=auto",
            "-o", "ControlPersist=60",
            f"{SSH_USER}@{ip}", cmd
        ], capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    finally:
        SSH_SEMAPHORE.release()

# -- Page 1 SYSTEM workers --
def _ping_worker(num):
    page = "system"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running")
        alive, lat = ping_ip(node_ip(num))
        set_job(page, num, "ok" if alive else "error", lat)
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        j = jobs[page][num]
        bi_logger.log_system("ping", num, j["status"], j["msg"])
        job_locks[page][num].release()

def _internet_worker(num):
    page = "system"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "checking...")
        code, out, err = ssh_run(node_ip(num), "ping -c 1 -W 2 8.8.8.8 && echo OK", timeout=10)
        if code == 0: set_job(page, num, "ok", "inet ok")
        else: set_job(page, num, "error", "no internet")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "ssh timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        j = jobs[page][num]
        bi_logger.log_system("inet", num, j["status"], j["msg"])
        job_locks[page][num].release()

def _gitpull_worker(num):
    page = "system"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "git pull...")
        code, out, err = ssh_run(node_ip(num), f"cd {GIT_DIR} && git stash; git pull", timeout=30)
        if code == 0:
            msg = (out.split("\n")[-1])[:24] if out else "done"
            set_job(page, num, "ok", msg)
        else:
            set_job(page, num, "error", (err or out)[:40] or "git error")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        j = jobs[page][num]
        bi_logger.log_system("gitpull", num, j["status"], j["msg"])
        job_locks[page][num].release()

def _reboot_worker(num):
    page = "system"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "rebooting...")
        ssh_run(node_ip(num), "reboot", timeout=10)
        set_job(page, num, "ok", "reboot sent")
    except subprocess.TimeoutExpired:
        set_job(page, num, "ok", "reboot sent")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        j = jobs[page][num]
        bi_logger.log_system("reboot", num, j["status"], j["msg"])
        job_locks[page][num].release()

# -- Page 2 LED --
def _led_worker(num):
    page = "led"
    ip = node_ip(num)
    if not job_locks[page][num].acquire(blocking=False): return
    dt_up = LED_UP_SEC / LED_STEPS
    dt_dn = LED_DN_SEC / LED_STEPS
    try:
        set_job(page, num, "running", "starting srv...")
        # OSCサーバーが起動していなければtmuxで起動
        code, out, _ = ssh_run(ip,
            f"tmux has-session -t {LED_SERVER_SESSION} 2>/dev/null && echo ALIVE || echo DEAD", timeout=5)
        if "DEAD" in out:
            ssh_run(ip,
                f"tmux new-session -d -s {LED_SERVER_SESSION}", timeout=10)
            ssh_run(ip,
                f"tmux send-keys -t {LED_SERVER_SESSION} 'cd {GIT_DIR} && uv run python pca9685_osc_led_server.py --port {OSC_PORT}' Enter", timeout=10)
            time.sleep(2)

        set_job(page, num, "running", "fade up...")
        client = udp_client.SimpleUDPClient(ip, OSC_PORT)
        for i in range(LED_STEPS + 1):
            client.send_message("/led", float(i / LED_STEPS))
            time.sleep(dt_up)
        set_job(page, num, "running", "fade down...")
        for i in range(LED_STEPS, -1, -1):
            client.send_message("/led", float(i / LED_STEPS))
            time.sleep(dt_dn)
        client.send_message("/led", 0.0)
        set_job(page, num, "ok", "done / off")
    except Exception as e:
        set_job(page, num, "error", str(e)[:40])
    finally:
        try: udp_client.SimpleUDPClient(ip, OSC_PORT).send_message("/led", 0.0)
        except: pass
        j = jobs[page][num]
        bi_logger.log_led(num, j["status"], j["msg"])
        job_locks[page][num].release()

# -- Page 3 Sound --
def _sound_worker(num):
    page = "sound"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "playing...")
        code, out, err = ssh_run(node_ip(num), SOUND_CMD, timeout=20)
        if code == 0: set_job(page, num, "ok", "played")
        else: set_job(page, num, "error", (err or out)[:40] or "error")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        j = jobs[page][num]
        bi_logger.log_sound(num, j["status"], j["msg"])
        job_locks[page][num].release()

# -- Generic tmux workers (run / llm / tts) --
def _tmux_start(num, page):
    conf = TMUX_CONF[page]
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "starting...")
        ip = node_ip(num)
        ssh_run(ip, f"tmux kill-session -t {conf['session']} 2>/dev/null", timeout=5)
        time.sleep(0.3)
        cmd = f"tmux new-session -d -s {conf['session']} \\; set remain-on-exit on \\; send-keys '{conf['cmd']}' Enter"
        code, out, err = ssh_run(ip, cmd, timeout=30)
        if code == 0: set_job(page, num, "ok", "tmux started")
        else: set_job(page, num, "error", (err or out)[:40] or "start fail")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "ssh timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        j = jobs[page][num]
        if page == "run":
            bi_logger.log_run_start(num, j["status"], j["msg"])
        elif page == "llm":
            bi_logger.log_llm("start", num, j["status"], j["msg"])
        elif page == "tts":
            bi_logger.log_tts("start", num, j["status"], j["msg"])
        job_locks[page][num].release()

def _tmux_stop(num, page):
    conf = TMUX_CONF[page]
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "stopping...")
        ssh_run(node_ip(num), f"tmux kill-session -t {conf['session']} 2>/dev/null", timeout=10)
        set_job(page, num, "idle", "stopped")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "ssh timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        j = jobs[page][num]
        if page == "run":
            bi_logger.log_run_stop(num, j["status"], j["msg"])
        elif page == "llm":
            bi_logger.log_llm("stop", num, j["status"], j["msg"])
        elif page == "tts":
            bi_logger.log_tts("stop", num, j["status"], j["msg"])
        job_locks[page][num].release()

def _tmux_check(num, page):
    conf = TMUX_CONF[page]
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "checking...")
        code, out, err = ssh_run(node_ip(num),
            f"tmux has-session -t {conf['session']} 2>/dev/null && echo ALIVE || echo DEAD", timeout=10)
        if "ALIVE" in out: set_job(page, num, "ok", "running")
        else: set_job(page, num, "idle", "not running")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "ssh timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        j = jobs[page][num]
        if page == "run":
            bi_logger.log_run_check(num, j["status"], j["msg"])
        elif page == "llm":
            bi_logger.log_llm("check", num, j["status"], j["msg"])
        elif page == "tts":
            bi_logger.log_tts("check", num, j["status"], j["msg"])
        job_locks[page][num].release()

def _tmux_fetch_log(num, page):
    conf = TMUX_CONF[page]
    try:
        code, out, err = ssh_run(node_ip(num),
            f"tmux capture-pane -t {conf['session']} -p -S -100 2>/dev/null", timeout=10)
        with script_logs_lock:
            script_logs[page][num] = out if code == 0 else f"(no session)\n{err}"
    except Exception as e:
        with script_logs_lock:
            script_logs[page][num] = f"(error: {e})"

WORKERS = {
    "ping": _ping_worker, "inet": _internet_worker,
    "gitpull": _gitpull_worker, "reboot": _reboot_worker,
    "led": _led_worker, "sound": _sound_worker,
    "run_start": lambda n: _tmux_start(n, "run"),
    "run_stop": lambda n: _tmux_stop(n, "run"),
    "run_check": lambda n: _tmux_check(n, "run"),
    "llm_start": lambda n: _tmux_start(n, "llm"),
    "llm_stop": lambda n: _tmux_stop(n, "llm"),
    "llm_check": lambda n: _tmux_check(n, "llm"),
    "tts_start": lambda n: _tmux_start(n, "tts"),
    "tts_stop": lambda n: _tmux_stop(n, "tts"),
    "tts_check": lambda n: _tmux_check(n, "tts"),
}
def run_worker(action, num):
    fn = WORKERS.get(action)
    if fn: threading.Thread(target=fn, args=(num,), daemon=True).start()

# -- API --
@app.route("/api/status/<page>")
def api_status(page):
    return jsonify(jobs.get(page, {}))

@app.route("/api/run", methods=["POST"])
def api_run():
    d = request.json
    action = d.get("action", "")
    nums   = d.get("nums", [])
    # バッチ操作の見出し行をログに残す
    if nums:
        _ACTION_CATEGORY = {
            "ping": "system", "inet": "system", "gitpull": "system", "reboot": "system",
            "led": "led", "sound": "sound",
            "llm_start": "llm", "llm_stop": "llm", "llm_check": "llm",
            "tts_start": "tts", "tts_stop": "tts", "tts_check": "tts",
            "run_start": "run", "run_stop": "run", "run_check": "run",
        }
        cat = _ACTION_CATEGORY.get(action)
        if cat:
            bi_logger.log_batch(cat, action, len(nums))
    for num in nums:
        run_worker(action, int(num))
    return jsonify({"ok": True})

@app.route("/api/reset", methods=["POST"])
def api_reset():
    d = request.json
    page = d.get("page")
    for num in d.get("nums", []):
        n = int(num)
        if not is_running(page, n): set_job(page, n, "idle", "")
    return jsonify({"ok": True})

@app.route("/api/script_log/<page>/<int:num>")
def api_script_log(page, num):
    if page not in TMUX_CONF: return jsonify({"num": num, "log": ""})
    threading.Thread(target=_tmux_fetch_log, args=(num, page), daemon=True).start()
    time.sleep(0.1)
    with script_logs_lock:
        return jsonify({"num": num, "log": script_logs[page].get(num, "")})

@app.route("/api/script_logs", methods=["POST"])
def api_script_logs():
    d = request.json
    nums = d.get("nums", [])
    page = d.get("page", "run")
    if page not in TMUX_CONF: return jsonify({})
    threads = []
    for num in nums:
        t = threading.Thread(target=_tmux_fetch_log, args=(int(num), page), daemon=True)
        t.start(); threads.append(t)
    for t in threads: t.join(timeout=12)
    result = {}
    with script_logs_lock:
        for num in nums: result[int(num)] = script_logs[page].get(int(num), "")
    return jsonify(result)

@app.route("/api/send_test", methods=["POST"])
def api_send_test():
    d = request.json
    num = int(d.get("num", 1))
    text = d.get("text", "")
    try:
        r = subprocess.run(["python3", SEND_SCRIPT, "-H", node_ip(num), "-t", text],
            capture_output=True, text=True, timeout=15)
        ok = r.returncode == 0
        bi_logger.log_run_test_input(num, text, ok, r.stdout.strip(), r.stderr.strip())
        return jsonify({"ok": ok, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()})
    except subprocess.TimeoutExpired:
        bi_logger.log_run_test_input(num, text, False, "", "timeout")
        return jsonify({"ok": False, "stdout": "", "stderr": "timeout"})
    except Exception as e:
        bi_logger.log_run_test_input(num, text, False, "", str(e))
        return jsonify({"ok": False, "stdout": "", "stderr": str(e)})


@app.route("/api/debug_scrape/<int:num>")
def api_debug_scrape(num):
    """
    デバッグ用: ノードの RUN ログファイルの内容・パース結果を返す。
    /api/debug_scrape/41 のようにアクセスして確認する。
    """
    result = {"num": num, "raw_lines": [], "parsed": [], "unmatched": [], "error": None}
    try:
        code, out, err = ssh_run(
            node_ip(num),
            f"tail -n 100 {RUN_LOG_FILE} 2>/dev/null",
            timeout=12,
        )
        result["ssh_code"] = code
        result["ssh_err"]  = err[:200] if err else ""
        raw_lines = out.splitlines() if out else []
        result["raw_line_count"] = len(raw_lines)
        result["raw_lines"] = raw_lines[-30:]   # ANSIなしなのでそのまま表示

        for line in raw_lines:
            p = _parse_loguru(line)
            if not p:
                continue
            ts, level, msg = p
            entry = {"ts": ts, "level": level, "msg": msg[:120]}
            matched = None
            if _re.search(r"Added input:", msg):               matched = "SIGNAL_IN"
            elif _re.search(r"Generated text:", msg):          matched = "GENERATED"
            elif "Preparing WAV file" in msg:                  matched = "TTS_PREP"
            elif "WAV preparation failed" in msg:              matched = "TTS_FAIL"
            elif _re.search(r"Sent to Mixer PC:", msg):        matched = "SIGNAL_OUT"
            elif _re.search(r"Error in generation:", msg):     matched = "ERR_GEN"
            elif _re.search(r"Error in TTS", msg):             matched = "ERR_TTS"
            elif _re.search(r"Error in BI cycle:", msg):       matched = "ERR_CYCLE"
            elif "Auto-starting BI cycle" in msg:              matched = "STARTUP"
            elif "Starting BI system" in msg:                  matched = "STARTUP"
            elif _re.search(r"Rejected data", msg):            matched = "RELAY_REJ"
            entry["matched"] = matched
            if matched:
                result["parsed"].append(entry)
            else:
                result["unmatched"].append(entry)
    except Exception as e:
        result["error"] = str(e)
    return jsonify(result)


# ── ログファイル閲覧 API ──────────────────────────────────────────────

@app.route("/api/logdates")
def api_logdates():
    """ログが存在する日付一覧と、その日のファイル一覧を返す"""
    result = []
    if not os.path.isdir(bi_logger.LOG_ROOT):
        return jsonify(result)
    for d in sorted(os.listdir(bi_logger.LOG_ROOT), reverse=True):
        dpath = os.path.join(bi_logger.LOG_ROOT, d)
        if not os.path.isdir(dpath):
            continue
        files = sorted(f for f in os.listdir(dpath) if f.endswith(".txt"))
        if files:
            result.append({"date": d, "files": files})
    return jsonify(result)


@app.route("/api/logfile")
def api_logfile():
    """?date=YYYY-MM-DD&file=filename.txt の内容を返す"""
    date = request.args.get("date", "")
    fname = request.args.get("file", "")
    # パストラバーサル防止
    if not date or not fname or "/" in date or "/" in fname or ".." in fname:
        return jsonify({"error": "invalid params"}), 400
    path = os.path.join(bi_logger.LOG_ROOT, date, fname)
    if not os.path.isfile(path):
        return jsonify({"content": "", "lines": 0})
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"content": content, "lines": content.count("\n")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── HTML ──────────────────────────────────────────────────────────────────────
SHARED_CSS = """
:root{--bg:#0a0a0f;--panel:#111118;--border:#1e1e2e;--accent:#f0c040;--a2:#40c0f0;--dim:#444460;--text:#cccce0;--ok:#40f080;--ng:#f04040;--run:#40c0f0;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:'Barlow',sans-serif;min-height:100vh;}
header{display:flex;align-items:center;justify-content:space-between;padding:12px 20px;border-bottom:1px solid var(--border);background:var(--panel);flex-wrap:wrap;gap:8px;}
h1{font-family:'Share Tech Mono',monospace;font-size:1rem;color:var(--accent);letter-spacing:4px;}
.sub{font-family:'Share Tech Mono',monospace;font-size:.62rem;color:var(--dim);margin-top:2px;}
nav{display:flex;}
.nt{font-family:'Share Tech Mono',monospace;font-size:.68rem;padding:7px 14px;border:1px solid var(--border);color:var(--dim);text-decoration:none;transition:all .15s;}
.nt:hover{border-color:var(--a2);color:var(--a2);}
.nt.on{border-color:var(--accent);color:var(--accent);background:rgba(240,192,64,.06);}
.toolbar{display:flex;gap:8px;padding:10px 20px;background:#0d0d14;border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:center;}
.btn{font-family:'Share Tech Mono',monospace;font-size:.72rem;padding:6px 14px;border:1px solid var(--dim);background:transparent;color:var(--text);cursor:pointer;transition:all .15s;}
.btn:hover{border-color:var(--accent);color:var(--accent);}
.bp{border-color:var(--accent);color:var(--accent);}
.b2{border-color:var(--a2);color:var(--a2);}
.bd:hover{border-color:var(--ng)!important;color:var(--ng)!important;}
.clusters{padding:12px 20px;display:flex;flex-direction:column;gap:10px;}
.cluster{border:1px solid var(--border);}
.ch{display:flex;align-items:center;gap:10px;padding:7px 12px;background:#0d0d14;border-bottom:1px solid var(--border);flex-wrap:wrap;}
.ct{font-family:'Share Tech Mono',monospace;font-size:.75rem;color:var(--accent);letter-spacing:2px;}
.cs{font-family:'Share Tech Mono',monospace;font-size:.62rem;margin-left:auto;}
.ca{display:flex;gap:5px;}
.cb{font-family:'Share Tech Mono',monospace;font-size:.6rem;padding:4px 9px;border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;transition:all .12s;}
.cb:hover{border-color:var(--accent);color:var(--accent);}
.cb.c2:hover{border-color:var(--a2);color:var(--a2);}
.grid{display:grid;grid-template-columns:repeat(10,1fr);gap:1px;background:var(--border);padding:1px;}
.node{background:#0d0d13;padding:7px 4px;display:flex;flex-direction:column;gap:3px;align-items:center;min-height:68px;transition:background .2s;cursor:pointer;}
.node:hover{background:#121218!important;}
.node.st-ok{background:#071410;}.node.st-error{background:#140707;}.node.st-running{background:#07100d;}
.nn{font-family:'Share Tech Mono',monospace;font-size:.58rem;color:var(--dim);}
.dot{width:8px;height:8px;border-radius:50%;background:var(--dim);transition:all .3s;margin:2px 0;}
.st-ok .dot{background:var(--ok);box-shadow:0 0 5px rgba(64,240,128,.5);}
.st-error .dot{background:var(--ng);}.st-running .dot{background:var(--run);animation:blink .7s ease-in-out infinite;}
@keyframes blink{0%,100%{opacity:.2}50%{opacity:1}}
.nl{font-family:'Share Tech Mono',monospace;font-size:.5rem;color:var(--dim);text-align:center;word-break:break-all;line-height:1.3;}
.st-ok .nl{color:var(--ok);}.st-error .nl{color:var(--ng);}.st-running .nl{color:var(--run);}
.footer{font-family:'Share Tech Mono',monospace;font-size:.6rem;color:var(--dim);padding:6px 20px 12px;}
.node.selected{outline:2px solid var(--accent);outline-offset:-2px;}
.node.selected .nn{color:var(--accent);}
/* ── ログビューワー ── */
.lv-wrap{margin:0 0 0 0;border-top:2px solid var(--border);}
.lv-hdr{display:flex;align-items:center;gap:10px;padding:8px 20px;background:#0a0a12;cursor:pointer;user-select:none;}
.lv-hdr:hover{background:#0d0d18;}
.lv-title{font-family:'Share Tech Mono',monospace;font-size:.72rem;color:var(--a2);letter-spacing:2px;}
.lv-arrow{font-family:'Share Tech Mono',monospace;font-size:.6rem;color:var(--dim);transition:transform .2s;}
.lv-wrap.open .lv-arrow{transform:rotate(180deg);}
.lv-body{display:none;padding:12px 20px;background:#08080e;border-top:1px solid var(--border);}
.lv-wrap.open .lv-body{display:flex;flex-direction:column;gap:8px;}
.lv-ctrl{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
.lv-sel{font-family:'Share Tech Mono',monospace;font-size:.68rem;padding:5px 8px;background:#0d0d14;border:1px solid var(--border);color:var(--text);cursor:pointer;}
.lv-sel:focus{outline:none;border-color:var(--a2);}
.lv-btn{font-family:'Share Tech Mono',monospace;font-size:.62rem;padding:5px 12px;border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;}
.lv-btn:hover{border-color:var(--a2);color:var(--a2);}
.lv-btn.active{border-color:var(--ok);color:var(--ok);}
.lv-meta{font-family:'Share Tech Mono',monospace;font-size:.55rem;color:var(--dim);margin-left:auto;}
.lv-text{font-family:'Share Tech Mono',monospace;font-size:.58rem;color:#b0b0d0;background:#060609;border:1px solid var(--border);padding:10px;white-space:pre;overflow:auto;height:320px;line-height:1.5;}
"""

NAV_TABS = [("/","system","01 SYSTEM"),("/led","led","02 LED"),("/sound","sound","03 SOUND"),("/llm","llm","04 LLM"),("/tts","tts","05 TTS"),("/run","run","99 RUN"),("/terminal","terminal","SSH"),("/broadcast","broadcast","BROADCAST")]
def make_nav(current):
    return "".join(f'<a href="{u}" class="nt{" on" if p==current else ""}">{l}</a>' for u,p,l in NAV_TABS)

# ── ログビューワー共通 HTML + JS ──────────────────────────────────────
_PAGE_LOG_DEFAULT = {
    "system": "01_system_log.txt",
    "led":    "02_led_log.txt",
    "sound":  "03_sound_log.txt",
    "llm":    "04_llm_log.txt",
    "tts":    "05_tts_log.txt",
    "run":    "99_run_history.txt",
}

def _make_log_viewer(page_id: str) -> str:
    default_file = _PAGE_LOG_DEFAULT.get(page_id, "")
    return f"""
<div class="lv-wrap" id="lvWrap">
  <div class="lv-hdr" onclick="lvToggle()">
    <span class="lv-title">&#128193; FILE LOG VIEWER</span>
    <span class="lv-arrow" id="lvArrow">&#9660;</span>
    <span style="font-family:'Share Tech Mono',monospace;font-size:.55rem;color:var(--dim);margin-left:8px" id="lvHint">クリックで展開</span>
  </div>
  <div class="lv-body" id="lvBody">
    <div class="lv-ctrl">
      <select class="lv-sel" id="lvDate" onchange="lvOnDateChange()"><option value="">-- 日付 --</option></select>
      <select class="lv-sel" id="lvFile" onchange="lvLoad()"><option value="">-- ファイル --</option></select>
      <button class="lv-btn" id="lvRefBtn" onclick="lvLoad()">&#8635; RELOAD</button>
      <button class="lv-btn" id="lvAutoBtn" onclick="lvToggleAuto()">AUTO OFF</button>
      <button class="lv-btn" onclick="lvScrollBottom()">&#8595; BOTTOM</button>
      <span class="lv-meta" id="lvMeta"></span>
    </div>
    <pre class="lv-text" id="lvText">(ファイルを選択してください)</pre>
  </div>
</div>
<script>
(function(){{
  const DEFAULT_FILE = '{default_file}';
  let lvOpen = false, lvAutoOn = false, lvAutoTimer = null;
  function lvToggle(){{
    lvOpen = !lvOpen;
    document.getElementById('lvWrap').classList.toggle('open', lvOpen);
    document.getElementById('lvArrow').innerHTML = lvOpen ? '&#9650;' : '&#9660;';
    document.getElementById('lvHint').textContent = lvOpen ? '' : 'クリックで展開';
    if(lvOpen && !document.getElementById('lvDate').value) lvInitDates();
  }}
  async function lvInitDates(){{
    try{{
      const r = await fetch('/api/logdates');
      const data = await r.json();
      const sel = document.getElementById('lvDate');
      sel.innerHTML = '<option value="">-- 日付 --</option>';
      data.forEach(d => {{
        const o = document.createElement('option');
        o.value = d.date; o.textContent = d.date;
        sel.appendChild(o);
      }});
      // 今日の日付を自動選択
      if(data.length > 0){{
        sel.value = data[0].date;
        lvOnDateChange(data[0]);
      }}
    }}catch(e){{}}
  }}
  async function lvOnDateChange(preloaded){{
    const date = document.getElementById('lvDate').value;
    if(!date) return;
    let files;
    if(preloaded && preloaded.files){{
      files = preloaded.files;
    }} else {{
      try{{
        const r = await fetch('/api/logdates');
        const data = await r.json();
        const entry = data.find(d => d.date === date);
        files = entry ? entry.files : [];
      }}catch(e){{ files = []; }}
    }}
    const fsel = document.getElementById('lvFile');
    fsel.innerHTML = '<option value="">-- ファイル --</option>';
    files.forEach(f => {{
      const o = document.createElement('option');
      o.value = f; o.textContent = f;
      fsel.appendChild(o);
    }});
    // このページに対応するデフォルトファイルを自動選択
    if(DEFAULT_FILE && files.includes(DEFAULT_FILE)) fsel.value = DEFAULT_FILE;
    else if(files.length > 0) fsel.value = files[0];
    if(fsel.value) lvLoad();
  }}
  async function lvLoad(){{
    const date = document.getElementById('lvDate').value;
    const file = document.getElementById('lvFile').value;
    if(!date || !file) return;
    try{{
      const r = await fetch('/api/logfile?date='+encodeURIComponent(date)+'&file='+encodeURIComponent(file));
      const d = await r.json();
      const el = document.getElementById('lvText');
      const wasAtBottom = el.scrollHeight - el.clientHeight <= el.scrollTop + 20;
      el.textContent = d.content || '(空のファイル)';
      document.getElementById('lvMeta').textContent = d.lines + ' lines  |  ' + date + '/' + file;
      if(wasAtBottom) el.scrollTop = el.scrollHeight;
    }}catch(e){{}}
  }}
  function lvScrollBottom(){{
    const el = document.getElementById('lvText');
    el.scrollTop = el.scrollHeight;
  }}
  function lvToggleAuto(){{
    lvAutoOn = !lvAutoOn;
    const btn = document.getElementById('lvAutoBtn');
    btn.textContent = lvAutoOn ? 'AUTO ON' : 'AUTO OFF';
    btn.classList.toggle('active', lvAutoOn);
    if(lvAutoOn){{ lvAutoTimer = setInterval(lvLoad, 10000); }}
    else{{ clearInterval(lvAutoTimer); }}
  }}
  window.lvToggle = lvToggle;
  window.lvOnDateChange = lvOnDateChange;
  window.lvLoad = lvLoad;
  window.lvScrollBottom = lvScrollBottom;
  window.lvToggleAuto = lvToggleAuto;
}})();
</script>"""

# -- make_html for simple pages (LED, Sound) --
def make_html(page_id, title, subtitle, toolbar_html, cluster_btn_defs, js_actions):
    nav = make_nav(page_id)
    return f"""<!DOCTYPE html><html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BI MONITOR - {title}</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;500;700&display=swap" rel="stylesheet">
<style>{SHARED_CSS}</style></head><body>
<header><div><h1>&#9672; BI MONITOR</h1><div class="sub">{subtitle}</div></div><nav>{nav}</nav></header>
<div class="toolbar">{toolbar_html}<div style="flex:1"></div><span class="btn" id="summary" style="cursor:default;border-color:transparent">\u2014</span></div>
<div class="clusters" id="clusters"></div><div class="footer" id="footer"></div>
<script>
const PAGE='{page_id}';
const CL=Array.from({{length:10}},(_,i)=>({{s:i*10+1,e:i*10+10,l:`CLUSTER ${{String(i+1).padStart(2,'0')}} \u2014 NODE ${{i*10+1}}\u2013${{i*10+10}}`}}));
const CBTNS={cluster_btn_defs};let J={{}};
function build(){{const c=document.getElementById('clusters');c.innerHTML='';CL.forEach((cl,ci)=>{{const d=document.createElement('div');d.className='cluster';const ca=CBTNS.map(([a,cls,l])=>`<button class="cb ${{cls}}" onclick="cAct(${{ci}},'${{a}}')">${{l}}</button>`).join('');d.innerHTML=`<div class="ch"><div class="ct">${{cl.l}}</div><div class="cs" id="cs${{ci}}">\u2014</div><div class="ca">${{ca}}</div></div><div class="grid" id="cg${{ci}}"></div>`;c.appendChild(d);const g=document.getElementById('cg'+ci);for(let i=0;i<10;i++){{const n=cl.s+i;const nd=document.createElement('div');nd.className='node';nd.id='nd'+n;nd.title=`NODE ${{n}}`;nd.onclick=()=>toggleSel(n);nd.innerHTML=`<div class="nn">NODE ${{n}}</div><div class="dot"></div><div class="nl" id="nl${{n}}">\u2014</div>`;g.appendChild(nd);}}}});}}
function applyStatus(d){{J=d;let ok=0,ng=0,run=0,idle=0;for(let n=1;n<=100;n++){{const j=d[n]||{{status:'idle',msg:''}};const nd=document.getElementById('nd'+n),nl=document.getElementById('nl'+n);if(!nd)continue;nd.className='node st-'+j.status+(sel.has(n)?' selected':'');nl.textContent=j.msg||j.status;if(j.status==='ok')ok++;else if(j.status==='error')ng++;else if(j.status==='running')run++;else idle++;}}document.getElementById('summary').textContent=`OK:${{ok}} ERR:${{ng}} RUN:${{run}} IDLE:${{idle}}`;CL.forEach((cl,ci)=>{{let co=0,cn=0,cr=0;for(let i=0;i<10;i++){{const j=d[cl.s+i];if(!j)continue;if(j.status==='ok')co++;else if(j.status==='error')cn++;else if(j.status==='running')cr++;}}const el=document.getElementById('cs'+ci);if(el){{el.textContent=`${{co}}ok/${{cn}}err/${{cr}}run`;el.style.color=co===10?'var(--ok)':cn>0?'var(--ng)':cr>0?'var(--run)':'var(--dim)';}}}});document.getElementById('footer').textContent='LAST: '+new Date().toLocaleTimeString();}}
async function poll(){{try{{const r=await fetch('/api/status/'+PAGE);applyStatus(await r.json())}}catch(e){{}}}}
async function runNums(action,nums){{await fetch('/api/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action,page:PAGE,nums}})}});}}
async function resetNums(nums){{await fetch('/api/reset',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{page:PAGE,nums}})}});await poll();}}
function allNums(){{return Array.from({{length:100}},(_,i)=>i+1);}}
function clNums(ci){{const cl=CL[ci];return Array.from({{length:10}},(_,i)=>cl.s+i);}}
let sel=new Set();
function toggleSel(n){{const nd=document.getElementById('nd'+n);if(sel.has(n)){{sel.delete(n);nd.classList.remove('selected');}}else{{sel.add(n);nd.classList.add('selected');}}updSelBtn();}}
function selCluster(ci){{clNums(ci).forEach(n=>{{sel.add(n);const nd=document.getElementById('nd'+n);if(nd)nd.classList.add('selected');}});updSelBtn();}}
function clearSel(){{sel.forEach(n=>{{const nd=document.getElementById('nd'+n);if(nd)nd.classList.remove('selected');}});sel.clear();updSelBtn();}}
function selAll(){{for(let n=1;n<=100;n++){{sel.add(n);const nd=document.getElementById('nd'+n);if(nd)nd.classList.add('selected');}};updSelBtn();}}
function getSelNums(){{return sel.size>0?Array.from(sel):allNums();}}
function updSelBtn(){{const el=document.getElementById('selCount');if(el)el.textContent=sel.size>0?sel.size+' selected':'all';}}
{js_actions}
build();poll();setInterval(poll,1500);
</script>
{_make_log_viewer(page_id)}
</body></html>"""


# ── Page 1: SYSTEM ────────────────────────────────────────────────────────────
def make_system_html():
    nav = make_nav("system")
    return f"""<!DOCTYPE html><html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BI MONITOR - SYSTEM</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;500;700&display=swap" rel="stylesheet">
<style>{SHARED_CSS}
.mode-bar{{display:flex;gap:4px;align-items:center;padding:0 8px;}}
.mode-bar span{{font-family:'Share Tech Mono',monospace;font-size:.6rem;color:var(--dim);}}
.mbtn{{font-family:'Share Tech Mono',monospace;font-size:.6rem;padding:4px 10px;border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;transition:all .12s;}}
.mbtn:hover{{border-color:var(--a2);color:var(--a2);}}
.mbtn.on{{border-color:var(--accent);color:var(--accent);background:rgba(240,192,64,.08);}}
.mbtn.on.dng{{border-color:var(--ng);color:var(--ng);background:rgba(240,64,64,.08);}}
.sep{{width:1px;height:20px;background:var(--border);margin:0 4px;}}
</style></head><body>
<header><div><h1>&#9672; BI MONITOR</h1><div class="sub">SYSTEM \u2014 ping / inet / git pull / reboot</div></div><nav>{nav}</nav></header>
<div class="toolbar">
  <button class="btn bp" onclick="runNums('ping',allNums())">&#9654; PING ALL</button>
  <button class="btn b2" onclick="runNums('inet',allNums())">&#9654; INET ALL</button>
  <button class="btn" onclick="if(confirm('GIT PULL ALL 100 NODES?'))runNums('gitpull',allNums())">&#9654; GIT PULL ALL</button>
  <button class="btn bd" onclick="if(confirm('REBOOT ALL 100 NODES?\\n\u3053\u306e\u64cd\u4f5c\u306f\u5143\u306b\u623b\u305b\u307e\u305b\u3093'))runNums('reboot',allNums())">&#9888; REBOOT ALL</button>
  <button class="btn bd" onclick="resetNums(allNums())">RESET</button>
  <div class="sep"></div>
  <div class="mode-bar">
    <span>AUTO:</span>
    <button class="mbtn" id="autoBtn" onclick="toggleAuto()">OFF</button>
    <select class="mbtn" id="autoSec" onchange="resetAutoTimer()" style="padding:3px 4px;font-size:.58rem;border-color:var(--border);background:transparent;">
      <option value="30">30s</option><option value="60" selected>60s</option><option value="120">120s</option><option value="300">5m</option>
    </select>
    <span class="mbtn" id="autoCountdown" style="cursor:default;min-width:42px;text-align:center;border-color:transparent;color:var(--dim);font-size:.55rem">\u2014</span>
  </div>
  <div class="sep"></div>
  <div class="mode-bar">
    <span>CLICK:</span>
    <button class="mbtn on" id="m_ping" onclick="setMode('ping')">PING</button>
    <button class="mbtn" id="m_inet" onclick="setMode('inet')">INET</button>
    <button class="mbtn" id="m_reboot" onclick="setMode('reboot')">REBOOT</button>
  </div>
  <div style="flex:1"></div>
  <span class="btn" id="summary" style="cursor:default;border-color:transparent">\u2014</span>
</div>
<div class="clusters" id="clusters"></div>
<div class="footer" id="footer"></div>
<script>
const PAGE='system';
const CL=Array.from({{length:10}},(_,i)=>({{s:i*10+1,e:i*10+10,l:`CLUSTER ${{String(i+1).padStart(2,'0')}} \u2014 NODE ${{i*10+1}}\u2013${{i*10+10}}`}}));
let J={{}};
let clickMode='ping';
function setMode(m){{clickMode=m;['ping','inet','reboot'].forEach(k=>{{const el=document.getElementById('m_'+k);el.className=k===m?'mbtn on'+(k==='reboot'?' dng':''):'mbtn';}});}}
function allNums(){{return Array.from({{length:100}},(_,i)=>i+1);}}
function clNums(ci){{const cl=CL[ci];return Array.from({{length:10}},(_,i)=>cl.s+i);}}
async function runNums(action,nums){{await fetch('/api/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action,page:PAGE,nums}})}});}}
async function resetNums(nums){{await fetch('/api/reset',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{page:PAGE,nums}})}});await poll();}}
function build(){{
  const c=document.getElementById('clusters');c.innerHTML='';
  CL.forEach((cl,ci)=>{{
    const d=document.createElement('div');d.className='cluster';
    d.innerHTML=`<div class="ch"><div class="ct">${{cl.l}}</div><div class="cs" id="cs${{ci}}">\u2014</div><div class="ca"><button class="cb" onclick="cAct(${{ci}},'ping')">PING</button><button class="cb c2" onclick="cAct(${{ci}},'inet')">INET</button><button class="cb" onclick="cAct(${{ci}},'gitpull')">GIT</button><button class="cb" onclick="cAct(${{ci}},'reboot')">REBOOT</button><button class="cb c2" onclick="cAct(${{ci}},'reset')">RST</button></div></div><div class="grid" id="cg${{ci}}"></div>`;
    c.appendChild(d);
    const g=document.getElementById('cg'+ci);
    for(let i=0;i<10;i++){{const n=cl.s+i;const nd=document.createElement('div');nd.className='node';nd.id='nd'+n;nd.title=`NODE ${{n}} (10.0.0.${{n}})`;nd.onclick=()=>nodeClick(n);nd.innerHTML=`<div class="nn">NODE ${{n}}</div><div class="dot"></div><div class="nl" id="nl${{n}}">\u2014</div>`;g.appendChild(nd);}}
  }});
}}
async function cAct(ci,a){{
  if(a==='reset')await resetNums(clNums(ci));
  else if(a==='reboot'){{if(confirm('REBOOT CLUSTER '+(ci+1)+'?'))await runNums('reboot',clNums(ci));}}
  else if(a==='gitpull'){{if(confirm('GIT PULL CLUSTER '+(ci+1)+'?'))await runNums('gitpull',clNums(ci));}}
  else await runNums(a,clNums(ci));
}}
async function nodeClick(n){{
  if(J[n]&&J[n].status==='running')return;
  if(clickMode==='reboot'){{if(confirm('REBOOT NODE '+n+' (10.0.0.'+n+') ?'))await runNums('reboot',[n]);}}
  else await runNums(clickMode,[n]);
}}
function applyStatus(d){{
  J=d;let ok=0,ng=0,run=0,idle=0;
  for(let n=1;n<=100;n++){{const j=d[n]||{{status:'idle',msg:''}};const nd=document.getElementById('nd'+n),nl=document.getElementById('nl'+n);if(!nd)continue;nd.className='node st-'+j.status;nl.textContent=j.msg||j.status;if(j.status==='ok')ok++;else if(j.status==='error')ng++;else if(j.status==='running')run++;else idle++;}}
  document.getElementById('summary').textContent=`OK:${{ok}} ERR:${{ng}} RUN:${{run}} IDLE:${{idle}}`;
  CL.forEach((cl,ci)=>{{let co=0,cn=0,cr=0;for(let i=0;i<10;i++){{const j=d[cl.s+i];if(!j)continue;if(j.status==='ok')co++;else if(j.status==='error')cn++;else if(j.status==='running')cr++;}}const el=document.getElementById('cs'+ci);if(el){{el.textContent=`${{co}}ok/${{cn}}err/${{cr}}run`;el.style.color=co===10?'var(--ok)':cn>0?'var(--ng)':cr>0?'var(--run)':'var(--dim)';}}}});
  document.getElementById('footer').textContent='LAST: '+new Date().toLocaleTimeString();
}}
async function poll(){{try{{const r=await fetch('/api/status/'+PAGE);applyStatus(await r.json())}}catch(e){{}}}}
let autoOn=false, autoTimer=null, countTimer=null, countdown=0;
function toggleAuto(){{
  autoOn=!autoOn;
  const btn=document.getElementById('autoBtn');
  btn.textContent=autoOn?'ON':'OFF';
  btn.className=autoOn?'mbtn on':'mbtn';
  if(autoOn){{ doPingAll(); startAutoTimer(); }}
  else{{ clearInterval(autoTimer); clearInterval(countTimer); autoTimer=null; countTimer=null; document.getElementById('autoCountdown').textContent='\u2014'; }}
}}
function doPingAll(){{ runNums('ping',allNums()); }}
function startAutoTimer(){{
  clearInterval(autoTimer); clearInterval(countTimer);
  const sec=parseInt(document.getElementById('autoSec').value)||60;
  countdown=sec;
  document.getElementById('autoCountdown').textContent=countdown+'s';
  countTimer=setInterval(()=>{{
    countdown--;
    if(countdown<0) countdown=sec;
    document.getElementById('autoCountdown').textContent=countdown+'s';
  }},1000);
  autoTimer=setInterval(()=>{{
    if(autoOn){{ doPingAll(); countdown=sec; }}
  }},sec*1000);
}}
function resetAutoTimer(){{ if(autoOn) startAutoTimer(); }}
build();poll();setInterval(poll,1500);
</script>
{_make_log_viewer("system")}
</body></html>"""


# ── Page 4: RUN SCRIPTS ──────────────────────────────────────────────────────
def make_tmux_html(page_id, title, subtitle, action_prefix, show_test=False):
    nav = make_nav(page_id)
    test_panel = ""
    test_js = ""
    if show_test:
        test_panel = f"""
<div class="test-panel">
  <label>SEND TEST:</label><label>NODE</label>
  <input type="number" id="testNum" value="1" min="1" max="100">
  <input type="text" id="testText" placeholder="テキストを入力... (例: 森林の奥深くには)" value="森林の奥深くには">
  <button class="btn b2" onclick="sendTest()">SEND</button>
</div>
<div class="test-result" id="testResult"></div>"""
        test_js = """
async function sendTest(){
  const num=document.getElementById('testNum').value;
  const text=document.getElementById('testText').value;
  const el=document.getElementById('testResult');
  el.className='test-result';el.textContent='sending to NODE '+num+' ...';
  try{
    const r=await fetch('/api/send_test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({num,text})});
    const d=await r.json();
    if(d.ok){el.className='test-result ok';el.textContent='NODE '+num+': OK '+d.stdout;}
    else{el.className='test-result err';el.textContent='NODE '+num+': ERR '+(d.stderr||d.stdout);}
  }catch(e){el.className='test-result err';el.textContent='Error: '+e;}
}"""
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BI MONITOR — {title}</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;500;700&display=swap" rel="stylesheet">
<style>
{SHARED_CSS}
.test-panel{{
  margin:0 20px 10px;padding:12px 16px;border:1px solid var(--border);background:var(--panel);
  display:flex;gap:10px;align-items:center;flex-wrap:wrap;
}}
.test-panel label{{font-family:'Share Tech Mono',monospace;font-size:.7rem;color:var(--a2);}}
.test-panel input[type=number]{{
  width:60px;padding:5px 8px;background:#0a0a0f;border:1px solid var(--border);
  color:var(--text);font-family:'Share Tech Mono',monospace;font-size:.72rem;
}}
.test-panel input[type=text]{{
  flex:1;min-width:200px;padding:5px 10px;background:#0a0a0f;border:1px solid var(--border);
  color:var(--text);font-family:'Share Tech Mono',monospace;font-size:.72rem;
}}
.test-panel input:focus{{outline:none;border-color:var(--a2);}}
.test-result{{
  font-family:'Share Tech Mono',monospace;font-size:.6rem;color:var(--dim);
  margin:0 20px 6px;padding:4px 10px;
}}
.test-result.ok{{color:var(--ok);}}.test-result.err{{color:var(--ng);}}
.log-toggle{{
  font-family:'Share Tech Mono',monospace;font-size:.58rem;padding:3px 8px;
  border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;transition:all .12s;
}}
.log-toggle:hover{{border-color:var(--a2);color:var(--a2);}}
.log-toggle.active{{border-color:var(--a2);color:var(--a2);}}
.log-area{{display:none;margin:0;padding:0;border-top:1px solid var(--border);}}
.log-area.open{{display:block;}}
.log-inner{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1px;background:var(--border);}}
.log-node{{background:#0a0a0f;padding:6px 8px;min-height:80px;}}
.log-node-hd{{
  font-family:'Share Tech Mono',monospace;font-size:.58rem;color:var(--accent);
  margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;
}}
.log-node-hd .refresh-btn{{
  font-size:.5rem;padding:1px 5px;border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;
}}
.log-node-hd .refresh-btn:hover{{border-color:var(--a2);color:var(--a2);}}
.log-text{{
  font-family:'Share Tech Mono',monospace;font-size:.5rem;color:#b0b0d0;
  white-space:pre-wrap;word-break:break-all;line-height:1.4;max-height:150px;overflow-y:auto;
}}
</style>
</head>
<body>
<header>
  <div><h1>&#9672; BI MONITOR</h1><div class="sub">{subtitle}</div></div>
  <nav>{nav}</nav>
</header>
<div class="toolbar">
  <button class="btn bp" onclick="runNums('{action_prefix}_start',getSelNums())">&#9654; START</button>
  <button class="btn bd" onclick="if(confirm('選択ノードを停止しますか?'))runNums('{action_prefix}_stop',getSelNums())">&#9632; STOP</button>
  <button class="btn b2" onclick="runNums('{action_prefix}_check',getSelNums())">&#8635; CHECK</button>
  <button class="btn" onclick="resetNums(getSelNums())">RESET</button>
  <button class="btn b2" onclick="selAll()">SELECT ALL</button>
  <button class="btn" onclick="clearSel()">CLEAR</button>
  <span class="btn" id="selCount" style="cursor:default;border-color:var(--accent);color:var(--accent);font-size:.6rem">all</span>
  <div style="flex:1"></div>
  <span class="btn" id="summary" style="cursor:default;border-color:transparent">—</span>
</div>
{test_panel}
<div class="clusters" id="clusters"></div>
<div class="footer" id="footer"></div>
<script>
const PAGE='{page_id}';
const ACT='{action_prefix}';
const CL=Array.from({{length:10}},(_,i)=>({{s:i*10+1,e:i*10+10,l:`CLUSTER ${{String(i+1).padStart(2,'0')}} \u2014 NODE ${{i*10+1}}\u2013${{i*10+10}}`}}));
let J={{}};
let sel=new Set();
function toggleSel(n){{const nd=document.getElementById('nd'+n);if(sel.has(n)){{sel.delete(n);nd.classList.remove('selected');}}else{{sel.add(n);nd.classList.add('selected');}}updSelBtn();}}
function selCluster(ci){{clNums(ci).forEach(n=>{{sel.add(n);const nd=document.getElementById('nd'+n);if(nd)nd.classList.add('selected');}});updSelBtn();}}
function clearSel(){{sel.forEach(n=>{{const nd=document.getElementById('nd'+n);if(nd)nd.classList.remove('selected');}});sel.clear();updSelBtn();}}
function selAll(){{for(let n=1;n<=100;n++){{sel.add(n);const nd=document.getElementById('nd'+n);if(nd)nd.classList.add('selected');}};updSelBtn();}}
function getSelNums(){{return sel.size>0?Array.from(sel):allNums();}}
function updSelBtn(){{const el=document.getElementById('selCount');if(el)el.textContent=sel.size>0?sel.size+' selected':'all';}}
function allNums(){{return Array.from({{length:100}},(_,i)=>i+1);}}
function clNums(ci){{const cl=CL[ci];return Array.from({{length:10}},(_,i)=>cl.s+i);}}
async function runNums(action,nums){{await fetch('/api/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action,page:PAGE,nums}})}});}}
async function resetNums(nums){{await fetch('/api/reset',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{page:PAGE,nums}})}});await poll();}}
{test_js}
function build(){{
  const c=document.getElementById('clusters');c.innerHTML='';
  CL.forEach((cl,ci)=>{{
    const d=document.createElement('div');d.className='cluster';
    d.innerHTML=`
      <div class="ch">
        <div class="ct">${{cl.l}}</div>
        <div class="cs" id="cs${{ci}}">—</div>
        <div class="ca">
          <button class="cb" onclick="runNums(ACT+'_start',clNums(${{ci}}))">START</button>
          <button class="cb" onclick="runNums(ACT+'_stop',clNums(${{ci}}))">STOP</button>
          <button class="cb c2" onclick="runNums(ACT+'_check',clNums(${{ci}}))">CHECK</button>
          <button class="cb c2" onclick="resetNums(clNums(${{ci}}))">RST</button>
          <button class="cb" onclick="selCluster(${{ci}})">SEL</button>
          <button class="log-toggle" id="lt${{ci}}" onclick="toggleLog(${{ci}})">LOG ▼</button>
        </div>
      </div>
      <div class="grid" id="cg${{ci}}"></div>
      <div class="log-area" id="la${{ci}}">
        <div class="log-inner" id="li${{ci}}"></div>
      </div>`;
    c.appendChild(d);
    const g=document.getElementById('cg'+ci);
    for(let i=0;i<10;i++){{
      const n=cl.s+i;
      const nd=document.createElement('div');
      nd.className='node';nd.id='nd'+n;
      nd.title=`NODE ${{n}} (10.0.0.${{n}})`;
      nd.onclick=()=>toggleSel(n);
      nd.innerHTML=`<div class="nn">NODE ${{n}}</div><div class="dot"></div><div class="nl" id="nl${{n}}">—</div>`;
      g.appendChild(nd);
    }}
    const li=document.getElementById('li'+ci);
    for(let i=0;i<10;i++){{
      const n=cl.s+i;
      const ld=document.createElement('div');ld.className='log-node';ld.id='ln'+n;
      ld.innerHTML=`<div class="log-node-hd"><span>NODE ${{n}} (10.0.0.${{n}})</span><button class="refresh-btn" onclick="event.stopPropagation();refreshLog(${{n}})">↻</button></div><div class="log-text" id="logtext${{n}}">—</div>`;
      li.appendChild(ld);
    }}
  }});
}}
function toggleLog(ci){{
  const la=document.getElementById('la'+ci);
  const lt=document.getElementById('lt'+ci);
  const isOpen=la.classList.toggle('open');
  lt.textContent=isOpen?'LOG ▲':'LOG ▼';
  lt.classList.toggle('active',isOpen);
  if(isOpen)fetchClusterLogs(ci);
}}
async function fetchClusterLogs(ci){{
  const nums=clNums(ci);
  try{{
    const r=await fetch('/api/script_logs',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{nums,page:PAGE}})}});
    const d=await r.json();
    for(const[n,log] of Object.entries(d)){{
      const el=document.getElementById('logtext'+n);
      if(el){{el.textContent=log||'(empty)';el.scrollTop=el.scrollHeight;}}
    }}
  }}catch(e){{}}
}}
async function refreshLog(n){{
  try{{
    const r=await fetch('/api/script_log/'+PAGE+'/'+n);
    const d=await r.json();
    const el=document.getElementById('logtext'+n);
    if(el){{el.textContent=d.log||'(empty)';el.scrollTop=el.scrollHeight;}}
  }}catch(e){{}}
}}
function applyStatus(d){{
  J=d;let ok=0,ng=0,run=0,idle=0;
  for(let n=1;n<=100;n++){{
    const j=d[n]||{{status:'idle',msg:''}};
    const nd=document.getElementById('nd'+n),nl=document.getElementById('nl'+n);
    if(!nd)continue;
    nd.className='node st-'+j.status+(sel.has(n)?' selected':'');
    nl.textContent=j.msg||j.status;
    if(j.status==='ok')ok++;else if(j.status==='error')ng++;else if(j.status==='running')run++;else idle++;
  }}
  document.getElementById('summary').textContent=`OK:${{ok}} ERR:${{ng}} RUN:${{run}} IDLE:${{idle}}`;
  CL.forEach((cl,ci)=>{{
    let co=0,cn=0,cr=0;
    for(let i=0;i<10;i++){{const j=d[cl.s+i];if(!j)continue;if(j.status==='ok')co++;else if(j.status==='error')cn++;else if(j.status==='running')cr++;}}
    const el=document.getElementById('cs'+ci);
    if(el){{el.textContent=`${{co}}ok/${{cn}}err/${{cr}}run`;el.style.color=co===10?'var(--ok)':cn>0?'var(--ng)':cr>0?'var(--run)':'var(--dim)';}}
  }});
  document.getElementById('footer').textContent='LAST: '+new Date().toLocaleTimeString();
}}
async function poll(){{try{{const r=await fetch('/api/status/'+PAGE);applyStatus(await r.json())}}catch(e){{}}}}
async function autoRefreshLogs(){{
  for(let ci=0;ci<10;ci++){{
    const la=document.getElementById('la'+ci);
    if(la&&la.classList.contains('open'))await fetchClusterLogs(ci);
  }}
}}
build();poll();
setInterval(poll,2000);
setInterval(autoRefreshLogs,5000);
</script>
{_make_log_viewer(page_id)}
</body>
</html>"""


# ── Static pages ─────────────────────────────────────────────────────────────
PAGES_HTML = {
    "led": make_html("led", "LED CHECK",
            "\u70b9\u706f\u78ba\u8a8d \u2014 \u30d5\u30a7\u30fc\u30c9\u30a2\u30c3\u30d7\u2192\u30d5\u30a7\u30fc\u30c9\u30c0\u30a6\u30f3\uff08\u5fc5\u305aOFF\u306b\u623b\u3057\u307e\u3059\uff09",
            '<button class="btn bp" onclick="runNums(\'led\',getSelNums())">&#9654; RUN</button>'
            '<button class="btn b2" onclick="selAll()">SELECT ALL</button>'
            '<button class="btn" onclick="clearSel()">CLEAR</button>'
            '<button class="btn bd" onclick="resetNums(getSelNums())">RESET</button>'
            '<span class="btn" id="selCount" style="cursor:default;border-color:var(--accent);color:var(--accent);font-size:.6rem">all</span>',
            '[["led","","RUN"],["sel","c2","SEL"],["reset","","RST"]]',
            """
    async function cAct(ci,a){
      if(a==='reset')await resetNums(clNums(ci));
      else if(a==='sel')selCluster(ci);
      else await runNums('led',clNums(ci));
    }
    """),
    "sound": make_html("sound", "SOUND CHECK",
            "\u30b5\u30a6\u30f3\u30c9\u30c1\u30a7\u30c3\u30af \u2014 tinyplay",
            '<button class="btn bp" onclick="runNums(\'sound\',getSelNums())">&#9654; PLAY</button>'
            '<button class="btn b2" onclick="selAll()">SELECT ALL</button>'
            '<button class="btn" onclick="clearSel()">CLEAR</button>'
            '<button class="btn bd" onclick="resetNums(getSelNums())">RESET</button>'
            '<span class="btn" id="selCount" style="cursor:default;border-color:var(--accent);color:var(--accent);font-size:.6rem">all</span>',
            '[["sound","","PLAY"],["sel","c2","SEL"],["reset","","RST"]]',
            """
    async function cAct(ci,a){
      if(a==='reset')await resetNums(clNums(ci));
      else if(a==='sel')selCluster(ci);
      else await runNums('sound',clNums(ci));
    }
    """),
}

@app.route("/")
def page_system(): return make_system_html()
@app.route("/led")
def page_led(): return PAGES_HTML["led"]
@app.route("/sound")
def page_sound(): return PAGES_HTML["sound"]
@app.route("/llm")
def page_llm(): return make_tmux_html("llm", "LLM CHECK", "LLMロード検証 — check_llm.py", "llm")
@app.route("/tts")
def page_tts(): return make_tmux_html("tts", "TTS CHECK", "TTSロード検証 — check_tts.py", "tts")
@app.route("/run")
def page_run(): return make_tmux_html("run", "RUN SCRIPTS", "スクリプト実行 (tmux) — SSH切断後も継続", "run", show_test=True)

@app.route("/terminal")
def page_terminal(): return make_terminal_html()
@app.route("/broadcast")
def page_broadcast(): return make_broadcast_html()


# ── Page 7: TERMINAL (Interactive SSH) ─────────────────────────────────────
def make_terminal_html():
    nav = make_nav("terminal")
    return f"""<!DOCTYPE html><html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BI MONITOR — SSH TERMINAL</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.min.css">
<script src="https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-web-links@0.9.0/lib/xterm-addon-web-links.min.js"></script>
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<style>
{SHARED_CSS}
.term-bar{{display:flex;align-items:center;gap:10px;padding:8px 20px;background:#0d0d14;border-bottom:1px solid var(--border);}}
.term-bar label{{font-family:'Share Tech Mono',monospace;font-size:.65rem;color:var(--dim);letter-spacing:1px;}}
.term-bar select,.term-bar input{{background:#0a0a0f;border:1px solid var(--border);color:var(--text);font-family:'Share Tech Mono',monospace;font-size:.72rem;padding:5px 8px;}}
.term-bar select:focus,.term-bar input:focus{{outline:none;border-color:var(--a2);}}
.term-bar select{{min-width:200px;}}
.tbtn{{font-family:'Share Tech Mono',monospace;font-size:.68rem;padding:5px 14px;border:1px solid var(--dim);background:transparent;color:var(--text);cursor:pointer;transition:all .15s;}}
.tbtn:hover{{border-color:var(--accent);color:var(--accent);}}
.tbtn-connect{{border-color:var(--ok);color:var(--ok);}}
.tbtn-connect:hover{{background:rgba(64,240,128,.08);}}
.tbtn-disconnect{{border-color:var(--ng);color:var(--ng);}}
.tbtn-disconnect:hover{{background:rgba(240,64,64,.08);}}
.term-status{{font-family:'Share Tech Mono',monospace;font-size:.6rem;color:var(--dim);margin-left:auto;display:flex;align-items:center;gap:6px;}}
.sdot{{width:6px;height:6px;border-radius:50%;background:var(--dim);}}
.sdot.on{{background:var(--ok);box-shadow:0 0 6px rgba(64,240,128,.5);}}
#terminal-wrap{{flex:1;padding:2px;background:#0a0a0f;overflow:hidden;}}
.term-page-body{{display:flex;flex-direction:column;height:calc(100vh - 95px);}}
</style></head><body>
<header><div><h1>&#9672; BI MONITOR</h1><div class="sub">SSH TERMINAL — 対話型リモートシェル</div></div><nav>{nav}</nav></header>
<div class="term-page-body">
<div class="term-bar">
  <label>DEVICE</label>
  <select id="tdev">
    {"".join(f'<optgroup label="CLUSTER {ci+1}">' + "".join(f'<option value="{ci*10+i+1}">NODE {ci*10+i+1} — 10.0.0.{ci*10+i+1}</option>' for i in range(10)) + '</optgroup>' for ci in range(10))}
  </select>
  <button class="tbtn tbtn-connect" id="btnConn" onclick="doConnect()">CONNECT</button>
  <button class="tbtn tbtn-disconnect" id="btnDisc" onclick="doDisconnect()" style="display:none">DISCONNECT</button>
  <div class="term-status"><span class="sdot" id="sDot"></span><span id="sText">Disconnected</span></div>
</div>
<div id="terminal-wrap"></div>
</div>
<script>
const socket = io();
let term, fitAddon, connected = false;

function initTerm() {{
  term = new Terminal({{
    fontFamily: "'Share Tech Mono', monospace",
    fontSize: 14,
    theme: {{
      background: '#0a0a0f', foreground: '#cccce0', cursor: '#f0c040', cursorAccent: '#0a0a0f',
      selectionBackground: 'rgba(240,192,64,0.2)',
      black:'#1e1e2e', red:'#f04040', green:'#40f080', yellow:'#f0c040',
      blue:'#40c0f0', magenta:'#c084fc', cyan:'#40c0f0', white:'#cccce0',
    }},
    cursorBlink: true, scrollback: 5000,
  }});
  fitAddon = new FitAddon.FitAddon();
  term.loadAddon(fitAddon);
  term.loadAddon(new WebLinksAddon.WebLinksAddon());
  term.open(document.getElementById('terminal-wrap'));
  fitAddon.fit();
  term.writeln('\\x1b[38;5;178m\\u2500\\u2500 PBG MONITOR SSH TERMINAL \\u2500\\u2500\\x1b[0m');
  term.writeln('\\x1b[38;5;244mSelect a device and click CONNECT\\x1b[0m\\r\\n');
  term.onData(data => {{ if(connected) socket.emit('ssh_input', {{data}}); }});
  window.addEventListener('resize', () => {{ fitAddon.fit(); if(connected) socket.emit('ssh_resize', {{cols:term.cols, rows:term.rows}}); }});
  new ResizeObserver(() => fitAddon.fit()).observe(document.getElementById('terminal-wrap'));
}}

function doConnect() {{
  const id = document.getElementById('tdev').value;
  term.clear();
  socket.emit('ssh_connect', {{device_id: parseInt(id)}});
}}
function doDisconnect() {{ socket.emit('ssh_disconnect'); }}

socket.on('ssh_status', d => term.writeln('\\x1b[38;5;244m' + d.message + '\\x1b[0m'));
socket.on('ssh_connected', d => {{
  connected = true;
  document.getElementById('btnConn').style.display = 'none';
  document.getElementById('btnDisc').style.display = '';
  document.getElementById('sDot').classList.add('on');
  document.getElementById('sText').textContent = 'NODE ' + d.device_id + ' (10.0.0.' + d.device_id + ')';
  socket.emit('ssh_resize', {{cols:term.cols, rows:term.rows}});
}});
socket.on('ssh_output', d => term.write(d.data));
socket.on('ssh_disconnected', () => {{
  if(connected) {{
    connected = false;
    document.getElementById('btnConn').style.display = '';
    document.getElementById('btnDisc').style.display = 'none';
    document.getElementById('sDot').classList.remove('on');
    document.getElementById('sText').textContent = 'Disconnected';
    term.writeln('\\r\\n\\x1b[38;5;167m\\u2500 Session ended \\u2500\\x1b[0m\\r\\n');
  }}
}});
socket.on('ssh_error', d => {{
  term.writeln('\\r\\n\\x1b[38;5;167mError: ' + d.message + '\\x1b[0m\\r\\n');
}});

initTerm();
</script></body></html>"""


# ── Page 8: BROADCAST ──────────────────────────────────────────────────────────
def make_broadcast_html():
    nav = make_nav("broadcast")
    return f"""<!DOCTYPE html><html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BI MONITOR — BROADCAST</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;500;700&display=swap" rel="stylesheet">
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<style>
{SHARED_CSS}
.bc-page{{display:flex;height:calc(100vh - 52px);overflow:hidden;}}
.bc-side{{width:340px;min-width:340px;background:var(--panel);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow-y:auto;}}
.bc-sec{{padding:14px 16px;border-bottom:1px solid var(--border);}}
.bc-sec-t{{font-family:'Share Tech Mono',monospace;font-size:.62rem;color:var(--dim);letter-spacing:2px;margin-bottom:8px;}}
.sopt{{display:flex;align-items:center;gap:8px;padding:6px 8px;margin-bottom:3px;border-radius:3px;cursor:pointer;font-family:'Share Tech Mono',monospace;font-size:.72rem;color:var(--text);}}
.sopt:hover{{background:rgba(255,255,255,.03);}}
.sopt input[type=radio]{{accent-color:var(--accent);}}
.ssub{{margin-left:26px;margin-top:6px;}}
.ssub select,.ssub input{{width:100%;background:#0a0a0f;border:1px solid var(--border);color:var(--text);font-family:'Share Tech Mono',monospace;font-size:.68rem;padding:5px 8px;}}
.ssub select:focus,.ssub input:focus{{outline:none;border-color:var(--a2);}}
.cmd-area textarea{{width:100%;min-height:80px;background:#0a0a0f;border:1px solid var(--border);color:var(--text);font-family:'Share Tech Mono',monospace;font-size:.72rem;padding:8px;resize:vertical;}}
.cmd-area textarea:focus{{outline:none;border-color:var(--a2);}}
.cmd-area textarea::placeholder{{color:var(--dim);}}
.cmd-btns{{display:flex;gap:6px;margin-top:8px;}}
.bcbtn{{flex:1;font-family:'Share Tech Mono',monospace;font-size:.68rem;font-weight:700;padding:7px;border:1px solid var(--accent);background:transparent;color:var(--accent);cursor:pointer;transition:all .15s;}}
.bcbtn:hover{{background:rgba(240,192,64,.08);}}
.bcbtn:disabled{{opacity:.3;cursor:not-allowed;}}
.bcbtn-save{{flex:0;padding:7px 14px;border-color:var(--dim);color:var(--dim);font-weight:400;}}
.bcbtn-save:hover{{border-color:var(--text);color:var(--text);}}
.snip-list{{display:flex;flex-direction:column;gap:3px;}}
.snip-item{{display:flex;align-items:center;justify-content:space-between;padding:5px 8px;background:#0a0a0f;border:1px solid var(--border);cursor:pointer;font-family:'Share Tech Mono',monospace;font-size:.65rem;color:var(--text);transition:border-color .15s;}}
.snip-item:hover{{border-color:var(--a2);}}
.snip-del{{color:var(--dim);padding:2px 4px;cursor:pointer;font-size:.7rem;}}
.snip-del:hover{{color:var(--ng);}}
.bc-main{{flex:1;display:flex;flex-direction:column;overflow:hidden;}}
.bc-hdr{{display:flex;align-items:center;justify-content:space-between;padding:10px 20px;background:var(--panel);border-bottom:1px solid var(--border);}}
.bc-hdr h3{{font-family:'Share Tech Mono',monospace;font-size:.68rem;color:var(--dim);letter-spacing:2px;}}
.bc-prog{{font-family:'Share Tech Mono',monospace;font-size:.62rem;color:var(--dim);}}
.bc-body{{flex:1;overflow-y:auto;padding:10px 20px;display:flex;flex-direction:column;gap:6px;}}
.rc{{border:1px solid var(--border);}}
.rc-hd{{display:flex;align-items:center;gap:8px;padding:6px 10px;background:#0d0d14;border-bottom:1px solid var(--border);font-family:'Share Tech Mono',monospace;font-size:.65rem;cursor:pointer;user-select:none;}}
.rc-dot{{width:6px;height:6px;border-radius:50%;}}
.rc-dot.ok{{background:var(--ok);}}.rc-dot.fail{{background:var(--ng);}}
.rc-dev{{font-weight:700;color:var(--text);}}.rc-ip{{color:var(--dim);}}.rc-time{{margin-left:auto;color:var(--dim);font-size:.58rem;}}
.rc-body{{display:none;padding:8px 10px;font-family:'Share Tech Mono',monospace;font-size:.62rem;line-height:1.5;white-space:pre-wrap;word-break:break-all;color:var(--text);max-height:280px;overflow-y:auto;}}
.rc-body.open{{display:block;}}
.rc-stderr{{color:var(--ng);}}
.bc-empty{{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--dim);font-family:'Share Tech Mono',monospace;font-size:.72rem;gap:8px;}}
</style></head><body>
<header><div><h1>&#9672; BI MONITOR</h1><div class="sub">BROADCAST — コマンド一斉送信</div></div><nav>{nav}</nav></header>
<div class="bc-page">
<div class="bc-side">
  <div class="bc-sec">
    <div class="bc-sec-t">TARGET SCOPE</div>
    <label class="sopt"><input type="radio" name="scope" value="all"> All devices (100)</label>
    <label class="sopt"><input type="radio" name="scope" value="cluster" checked> Cluster</label>
    <div class="ssub" id="clSub">
      <select id="clSel">
        {"".join(f'<option value="{ci+1}">Cluster {ci+1} (NODE {ci*10+1}–{ci*10+10})</option>' for ci in range(10))}
      </select>
    </div>
    <label class="sopt"><input type="radio" name="scope" value="node"> Specific nodes</label>
    <div class="ssub" id="ndSub" style="display:none">
      <input type="text" id="ndInput" placeholder="e.g. 1,2,3 or 1-10 or 1-5,8">
    </div>
  </div>
  <div class="bc-sec cmd-area">
    <div class="bc-sec-t">COMMAND</div>
    <textarea id="bcCmd" placeholder="Enter shell command...&#10;e.g. uname -a&#10;e.g. pip install loguru"></textarea>
    <div class="cmd-btns">
      <button class="bcbtn" id="btnExec" onclick="doExec()">EXECUTE</button>
      <button class="bcbtn bcbtn-save" onclick="doSave()">SAVE</button>
    </div>
  </div>
  <div class="bc-sec" style="flex:1;overflow-y:auto;">
    <div class="bc-sec-t">SNIPPETS</div>
    <div class="snip-list" id="snipList"></div>
  </div>
</div>
<div class="bc-main">
  <div class="bc-hdr"><h3>RESULTS</h3><span class="bc-prog" id="bcProg"></span></div>
  <div class="bc-body" id="bcBody">
    <div class="bc-empty">&#9654; Execute a command to see results</div>
  </div>
</div>
</div>
<script>
const socket = io();
let running = false, rcvd = 0, total = 0;
let snippets = JSON.parse(localStorage.getItem('bi_snippets') || 'null') || [
  {{name:"System info", command:"uname -a && uptime"}},
  {{name:"Disk usage", command:"df -h /"}},
  {{name:"Service status", command:"systemctl status pbg --no-pager -l 2>/dev/null || echo no service"}},
  {{name:"Last 50 logs", command:"journalctl -u pbg -n 50 --no-pager 2>/dev/null || tail -50 /tmp/bi_run.log 2>/dev/null || echo 'no logs'"}},
  {{name:"Python packages", command:"pip list 2>/dev/null | head -30 || uv pip list 2>/dev/null | head -30"}},
  {{name:"Network", command:"ip addr show | grep 'inet '"}},
  {{name:"Git status", command:"cd {GIT_DIR} && git log --oneline -5 2>/dev/null || echo 'no repo'"}},
  {{name:"Restart BI", command:"tmux kill-session -t bi_main 2>/dev/null; echo 'killed'"}},
];
function saveSnippets(){{ localStorage.setItem('bi_snippets', JSON.stringify(snippets)); }}

document.querySelectorAll('input[name=scope]').forEach(r => r.addEventListener('change', () => {{
  document.getElementById('clSub').style.display = r.value==='cluster' ? '' : 'none';
  document.getElementById('ndSub').style.display = r.value==='node' ? '' : 'none';
}}));

function parseRange(s) {{
  const ids=[];
  for(const p of s.split(',')) {{
    const t=p.trim();
    if(t.includes('-')) {{ const[a,b]=t.split('-').map(Number); for(let i=a;i<=b;i++) ids.push(i); }}
    else if(t) ids.push(Number(t));
  }}
  return [...new Set(ids)].sort((a,b)=>a-b);
}}

function esc(s){{ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

function doExec() {{
  if(running) return;
  const cmd = document.getElementById('bcCmd').value.trim();
  if(!cmd) return;
  const scope = document.querySelector('input[name=scope]:checked').value;
  let sv = '';
  if(scope==='cluster') sv = document.getElementById('clSel').value;
  else if(scope==='node') {{
    const ids = parseRange(document.getElementById('ndInput').value);
    if(!ids.length) return;
    sv = ids.join(',');
  }}
  socket.emit('broadcast_command', {{command:cmd, scope, scope_value:sv}});
}}

socket.on('broadcast_start', d => {{
  running=true; rcvd=0; total=d.total;
  document.getElementById('btnExec').disabled=true;
  document.getElementById('bcBody').innerHTML='';
  document.getElementById('bcProg').textContent='0 / '+total;
}});

socket.on('broadcast_result', d => {{
  rcvd++;
  document.getElementById('bcProg').textContent = rcvd+' / '+total;
  const card = document.createElement('div'); card.className='rc';
  const hd = document.createElement('div'); hd.className='rc-hd';
  hd.innerHTML = '<span class="rc-dot '+(d.success?'ok':'fail')+'"></span>'
    +'<span class="rc-dev">#'+d.device_id+'</span>'
    +'<span class="rc-ip">10.0.0.'+d.device_id+'</span>'
    +'<span class="rc-time">'+d.elapsed+'s · exit '+d.exit_code+'</span>';
  const bd = document.createElement('div'); bd.className='rc-body';
  let content = '';
  if(d.stdout) content += esc(d.stdout);
  if(d.stderr) content += (content?'\\n':'')+'<span class="rc-stderr">'+esc(d.stderr)+'</span>';
  if(!content) content='<span style="color:var(--dim)">(no output)</span>';
  bd.innerHTML = content;
  hd.onclick = () => bd.classList.toggle('open');
  card.appendChild(hd); card.appendChild(bd);
  document.getElementById('bcBody').appendChild(card);
}});

socket.on('broadcast_done', d => {{
  running=false;
  document.getElementById('btnExec').disabled=false;
  document.getElementById('bcProg').textContent='Done: '+d.success+' ok, '+d.failed+' failed / '+d.total;
}});

socket.on('broadcast_error', d => {{
  running=false;
  document.getElementById('btnExec').disabled=false;
  document.getElementById('bcProg').textContent='Error: '+d.message;
}});

function renderSnippets() {{
  const el = document.getElementById('snipList'); el.innerHTML='';
  snippets.forEach((s,i) => {{
    const item = document.createElement('div'); item.className='snip-item';
    item.innerHTML = '<span>'+esc(s.name)+'</span><span class="snip-del" data-i="'+i+'">&#10005;</span>';
    item.onclick = e => {{
      if(e.target.classList.contains('snip-del')) {{ snippets.splice(parseInt(e.target.dataset.i),1); saveSnippets(); renderSnippets(); return; }}
      document.getElementById('bcCmd').value = s.command;
    }};
    el.appendChild(item);
  }});
}}
function doSave() {{
  const cmd = document.getElementById('bcCmd').value.trim();
  if(!cmd) return;
  const name = prompt('Snippet name:');
  if(!name) return;
  snippets.push({{name, command:cmd}}); saveSnippets(); renderSnippets();
}}
renderSnippets();
</script></body></html>"""


# ── SocketIO: Interactive SSH Terminal ─────────────────────────────────────
@socketio.on("ssh_connect")
def handle_ssh_connect(data):
    device_id = int(data.get("device_id", 0))
    sid = request.sid
    if device_id < 1 or device_id > NODE_COUNT:
        emit("ssh_error", {"message": f"Invalid device ID: {device_id}"})
        return
    emit("ssh_status", {"message": f"Connecting to NODE {device_id} (10.0.0.{device_id})..."})
    result = _ssh_open_interactive(sid, device_id)
    if result is not True:
        emit("ssh_error", {"message": f"SSH connection failed: {result}"})
        return
    emit("ssh_connected", {"device_id": device_id})
    def _reader():
        while True:
            with _ssh_lock:
                session = _ssh_sessions.get(sid)
            if not session or not session["active"]:
                break
            try:
                ch = session["channel"]
                if ch.recv_ready():
                    data = ch.recv(4096).decode("utf-8", errors="replace")
                    socketio.emit("ssh_output", {"data": data}, to=sid)
                else:
                    time.sleep(0.05)
            except Exception:
                time.sleep(0.05)
        socketio.emit("ssh_disconnected", {}, to=sid)
    threading.Thread(target=_reader, daemon=True).start()

@socketio.on("ssh_input")
def handle_ssh_input(data):
    sid = request.sid
    with _ssh_lock:
        session = _ssh_sessions.get(sid)
    if session and session["active"]:
        try: session["channel"].send(data.get("data", ""))
        except: pass

@socketio.on("ssh_resize")
def handle_ssh_resize(data):
    sid = request.sid
    with _ssh_lock:
        session = _ssh_sessions.get(sid)
    if session and session["active"]:
        try: session["channel"].resize_pty(width=int(data.get("cols",120)), height=int(data.get("rows",40)))
        except: pass

@socketio.on("ssh_disconnect")
def handle_ssh_disconnect():
    with _ssh_lock:
        _ssh_close_interactive(request.sid)
    emit("ssh_disconnected", {})

@socketio.on("disconnect")
def handle_ws_disconnect():
    with _ssh_lock:
        _ssh_close_interactive(request.sid)


# ── SocketIO: Command Broadcast ────────────────────────────────────────────
@socketio.on("broadcast_command")
def handle_broadcast(data):
    command = data.get("command", "").strip()
    scope = data.get("scope", "node")
    scope_value = data.get("scope_value", "")
    sid = request.sid
    if not command:
        emit("broadcast_error", {"message": "Empty command"}); return

    # Resolve targets
    targets = []
    if scope == "all":
        targets = list(range(1, NODE_COUNT + 1))
    elif scope == "cluster" and scope_value:
        cid = int(scope_value)
        targets = list(range((cid-1)*10+1, cid*10+1))
    elif scope == "node" and scope_value:
        targets = [int(x) for x in scope_value.split(",") if x.strip()]
    targets = [n for n in targets if 1 <= n <= NODE_COUNT]

    if not targets:
        emit("broadcast_error", {"message": "No targets"}); return
    emit("broadcast_start", {"total": len(targets), "command": command, "scope": scope})

    def _run_one(num):
        start = time.time()
        try:
            code, out, err = ssh_run(node_ip(num), command, timeout=30)
            elapsed = round(time.time() - start, 2)
            socketio.emit("broadcast_result", {
                "device_id": num, "host": node_ip(num),
                "exit_code": code, "stdout": out[-4096:], "stderr": err[-2048:],
                "success": code == 0, "elapsed": elapsed,
            }, to=sid)
        except Exception as e:
            elapsed = round(time.time() - start, 2)
            socketio.emit("broadcast_result", {
                "device_id": num, "host": node_ip(num),
                "exit_code": -1, "stdout": "", "stderr": str(e)[:512],
                "success": False, "elapsed": elapsed,
            }, to=sid)

    def _run_all():
        results = []
        lock = threading.Lock()
        def _tracked_run(num):
            _run_one(num)
            with lock:
                results.append(num)
        threads = []
        for n in targets:
            t = threading.Thread(target=_tracked_run, args=(n,), daemon=True)
            t.start(); threads.append(t)
        for t in threads:
            t.join(timeout=35)
        socketio.emit("broadcast_done", {
            "total": len(targets), "success": len(results), "failed": len(targets) - len(results),
        }, to=sid)

    threading.Thread(target=_run_all, daemon=True).start()


if __name__ == "__main__":
    # RUN ログスクレイパー起動
    threading.Thread(target=_run_scraper_loop, daemon=True, name="run-scraper").start()
    print("=" * 50)
    print("  BI MONITOR")
    print("  http://localhost:5050           -> 01 SYSTEM")
    print("  http://localhost:5050/led       -> 02 LED")
    print("  http://localhost:5050/sound     -> 03 SOUND")
    print("  http://localhost:5050/llm       -> 04 LLM")
    print("  http://localhost:5050/tts       -> 05 TTS")
    print("  http://localhost:5050/run       -> 99 RUN SCRIPTS")
    print("  http://localhost:5050/terminal  -> SSH TERMINAL")
    print("  http://localhost:5050/broadcast -> BROADCAST")
    print("=" * 50)
    socketio.run(app, host="0.0.0.0", port=5050, debug=False)
