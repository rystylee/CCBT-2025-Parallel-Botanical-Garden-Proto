"""
BI MONITOR - 4 pages
  /        -> Page 1: SYSTEM (ping + inet + git pull + reboot)
  /led     -> Page 2: LED
  /sound   -> Page 3: Sound
  /run     -> Page 4: Run Scripts (tmux)
"""
from flask import Flask, jsonify, request, render_template_string
from pythonosc import udp_client
import threading, time, subprocess, getpass

app = Flask(__name__)
NODE_PREFIX = "10.0.0"
NODE_COUNT  = 100
OSC_PORT    = 9000
SSH_USER    = "root"
GIT_DIR     = "/root/dev/CCBT-2025-Parallel-Botanical-Garden-Proto"
SOUND_CMD   = "tinyplay -D0 -d1 /usr/local/m5stack/logo.wav"
LED_STEPS   = 40
LED_UP_SEC  = 2.0
LED_DN_SEC  = 2.0
SSH_PASS = getpass.getpass("SSH Password: ")
TMUX_SESSION = "bi_main"
SCRIPT_CMD = f"cd {GIT_DIR} && git stash && git pull && uv run python main.py"
SEND_SCRIPT = "/home/yuma/dev/CCBT-2025-Parallel-Botanical-Garden-Proto/scripts/send_bi_input.py"

PAGES = ["system", "led", "sound", "run"]
jobs = {p: {n: {"status":"idle","msg":""} for n in range(1,NODE_COUNT+1)} for p in PAGES}
job_locks = {p: {n: threading.Lock() for n in range(1,NODE_COUNT+1)} for p in PAGES}
script_logs = {n: "" for n in range(1, NODE_COUNT+1)}
script_logs_lock = threading.Lock()

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
def ssh_run(ip, cmd, timeout=15):
    r = subprocess.run(["sshpass","-p",SSH_PASS,"ssh","-o","StrictHostKeyChecking=no","-o","ConnectTimeout=5",f"{SSH_USER}@{ip}",cmd], capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

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
        job_locks[page][num].release()

def _gitpull_worker(num):
    page = "system"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "git pull...")
        code, out, err = ssh_run(node_ip(num), f"cd {GIT_DIR} && git pull", timeout=30)
        if code == 0:
            msg = (out.split("\n")[-1])[:24] if out else "done"
            set_job(page, num, "ok", msg)
        else:
            set_job(page, num, "error", (err or out)[:24] or "git error")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
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
        job_locks[page][num].release()

# -- Page 2 LED --
def _led_worker(num):
    page = "led"
    ip = node_ip(num)
    if not job_locks[page][num].acquire(blocking=False): return
    dt_up = LED_UP_SEC / LED_STEPS
    dt_dn = LED_DN_SEC / LED_STEPS
    try:
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
        set_job(page, num, "error", str(e)[:20])
    finally:
        try: udp_client.SimpleUDPClient(ip, OSC_PORT).send_message("/led", 0.0)
        except: pass
        job_locks[page][num].release()

# -- Page 3 Sound --
def _sound_worker(num):
    page = "sound"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "playing...")
        code, out, err = ssh_run(node_ip(num), SOUND_CMD, timeout=20)
        if code == 0: set_job(page, num, "ok", "played")
        else: set_job(page, num, "error", (err or out)[:24] or "error")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        job_locks[page][num].release()

# -- Page 4 Run Scripts (tmux) --
def _run_start_worker(num):
    page = "run"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "starting...")
        ip = node_ip(num)
        ssh_run(ip, f"tmux kill-session -t {TMUX_SESSION} 2>/dev/null", timeout=5)
        time.sleep(0.3)
        code, out, err = ssh_run(ip, f"tmux new-session -d -s {TMUX_SESSION} '{SCRIPT_CMD}'", timeout=30)
        if code == 0: set_job(page, num, "ok", "tmux started")
        else: set_job(page, num, "error", (err or out)[:24] or "start fail")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "ssh timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        job_locks[page][num].release()

def _run_stop_worker(num):
    page = "run"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "stopping...")
        ssh_run(node_ip(num), f"tmux kill-session -t {TMUX_SESSION} 2>/dev/null", timeout=10)
        set_job(page, num, "idle", "stopped")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "ssh timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        job_locks[page][num].release()

def _run_check_worker(num):
    page = "run"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "checking...")
        code, out, err = ssh_run(node_ip(num),
            f"tmux has-session -t {TMUX_SESSION} 2>/dev/null && echo ALIVE || echo DEAD", timeout=10)
        if "ALIVE" in out: set_job(page, num, "ok", "running")
        else: set_job(page, num, "idle", "not running")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "ssh timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        job_locks[page][num].release()

def _fetch_log(num):
    try:
        code, out, err = ssh_run(node_ip(num),
            f"tmux capture-pane -t {TMUX_SESSION} -p -S -100 2>/dev/null", timeout=10)
        with script_logs_lock:
            script_logs[num] = out if code == 0 else f"(no session)\n{err}"
    except Exception as e:
        with script_logs_lock:
            script_logs[num] = f"(error: {e})"

WORKERS = {
    "ping": _ping_worker, "inet": _internet_worker,
    "gitpull": _gitpull_worker, "reboot": _reboot_worker,
    "led": _led_worker, "sound": _sound_worker,
    "run_start": _run_start_worker, "run_stop": _run_stop_worker,
    "run_check": _run_check_worker,
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
    for num in d.get("nums", []):
        run_worker(d.get("action"), int(num))
    return jsonify({"ok": True})

@app.route("/api/reset", methods=["POST"])
def api_reset():
    d = request.json
    page = d.get("page")
    for num in d.get("nums", []):
        n = int(num)
        if not is_running(page, n): set_job(page, n, "idle", "")
    return jsonify({"ok": True})

@app.route("/api/script_log/<int:num>")
def api_script_log(num):
    threading.Thread(target=_fetch_log, args=(num,), daemon=True).start()
    time.sleep(0.1)
    with script_logs_lock:
        return jsonify({"num": num, "log": script_logs.get(num, "")})

@app.route("/api/script_logs", methods=["POST"])
def api_script_logs():
    d = request.json
    nums = d.get("nums", [])
    threads = []
    for num in nums:
        t = threading.Thread(target=_fetch_log, args=(int(num),), daemon=True)
        t.start(); threads.append(t)
    for t in threads: t.join(timeout=12)
    result = {}
    with script_logs_lock:
        for num in nums: result[int(num)] = script_logs.get(int(num), "")
    return jsonify(result)

@app.route("/api/send_test", methods=["POST"])
def api_send_test():
    d = request.json
    num = int(d.get("num", 1))
    text = d.get("text", "")
    try:
        r = subprocess.run(["python3", SEND_SCRIPT, "-H", node_ip(num), "-t", text],
            capture_output=True, text=True, timeout=15)
        return jsonify({"ok": r.returncode==0, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "stdout": "", "stderr": "timeout"})
    except Exception as e:
        return jsonify({"ok": False, "stdout": "", "stderr": str(e)})


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
"""

NAV_TABS = [("/","system","01 SYSTEM"),("/led","led","02 LED"),("/sound","sound","03 SOUND"),("/run","run","04 RUN")]
def make_nav(current):
    return "".join(f'<a href="{u}" class="nt{" on" if p==current else ""}">{l}</a>' for u,p,l in NAV_TABS)

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
function build(){{const c=document.getElementById('clusters');c.innerHTML='';CL.forEach((cl,ci)=>{{const d=document.createElement('div');d.className='cluster';const ca=CBTNS.map(([a,cls,l])=>`<button class="cb ${{cls}}" onclick="cAct(${{ci}},'${{a}}')">${{l}}</button>`).join('');d.innerHTML=`<div class="ch"><div class="ct">${{cl.l}}</div><div class="cs" id="cs${{ci}}">\u2014</div><div class="ca">${{ca}}</div></div><div class="grid" id="cg${{ci}}"></div>`;c.appendChild(d);const g=document.getElementById('cg'+ci);for(let i=0;i<10;i++){{const n=cl.s+i;const nd=document.createElement('div');nd.className='node';nd.id='nd'+n;nd.title=`NODE ${{n}}`;nd.onclick=()=>nodeClick(n);nd.innerHTML=`<div class="nn">NODE ${{n}}</div><div class="dot"></div><div class="nl" id="nl${{n}}">\u2014</div>`;g.appendChild(nd);}}}});}}
function applyStatus(d){{J=d;let ok=0,ng=0,run=0,idle=0;for(let n=1;n<=100;n++){{const j=d[n]||{{status:'idle',msg:''}};const nd=document.getElementById('nd'+n),nl=document.getElementById('nl'+n);if(!nd)continue;nd.className='node st-'+j.status;nl.textContent=j.msg||j.status;if(j.status==='ok')ok++;else if(j.status==='error')ng++;else if(j.status==='running')run++;else idle++;}}document.getElementById('summary').textContent=`OK:${{ok}} ERR:${{ng}} RUN:${{run}} IDLE:${{idle}}`;CL.forEach((cl,ci)=>{{let co=0,cn=0,cr=0;for(let i=0;i<10;i++){{const j=d[cl.s+i];if(!j)continue;if(j.status==='ok')co++;else if(j.status==='error')cn++;else if(j.status==='running')cr++;}}const el=document.getElementById('cs'+ci);if(el){{el.textContent=`${{co}}ok/${{cn}}err/${{cr}}run`;el.style.color=co===10?'var(--ok)':cn>0?'var(--ng)':cr>0?'var(--run)':'var(--dim)';}}}});document.getElementById('footer').textContent='LAST: '+new Date().toLocaleTimeString();}}
async function poll(){{try{{const r=await fetch('/api/status/'+PAGE);applyStatus(await r.json())}}catch(e){{}}}}
async function runNums(action,nums){{await fetch('/api/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action,page:PAGE,nums}})}});}}
async function resetNums(nums){{await fetch('/api/reset',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{page:PAGE,nums}})}});await poll();}}
function allNums(){{return Array.from({{length:100}},(_,i)=>i+1);}}
function clNums(ci){{const cl=CL[ci];return Array.from({{length:10}},(_,i)=>cl.s+i);}}
{js_actions}
build();poll();setInterval(poll,1500);
</script></body></html>"""


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
  <button class="btn" onclick="runNums('gitpull',allNums())">&#9654; GIT PULL ALL</button>
  <button class="btn bd" onclick="if(confirm('REBOOT ALL 100 NODES?\\n\u3053\u306e\u64cd\u4f5c\u306f\u5143\u306b\u623b\u305b\u307e\u305b\u3093'))runNums('reboot',allNums())">&#9888; REBOOT ALL</button>
  <button class="btn bd" onclick="resetNums(allNums())">RESET</button>
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
build();poll();setInterval(poll,1500);
</script></body></html>"""


# ── Page 4: RUN SCRIPTS ──────────────────────────────────────────────────────
def make_run_html():
    nav = make_nav("run")
    return f"""<!DOCTYPE html><html lang="ja"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BI MONITOR - RUN SCRIPTS</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;500;700&display=swap" rel="stylesheet">
<style>
{SHARED_CSS}
.test-panel{{margin:0 20px 10px;padding:12px 16px;border:1px solid var(--border);background:var(--panel);display:flex;gap:10px;align-items:center;flex-wrap:wrap;}}
.test-panel label{{font-family:'Share Tech Mono',monospace;font-size:.7rem;color:var(--a2);}}
.test-panel input[type=number]{{width:60px;padding:5px 8px;background:#0a0a0f;border:1px solid var(--border);color:var(--text);font-family:'Share Tech Mono',monospace;font-size:.72rem;}}
.test-panel input[type=text]{{flex:1;min-width:200px;padding:5px 10px;background:#0a0a0f;border:1px solid var(--border);color:var(--text);font-family:'Share Tech Mono',monospace;font-size:.72rem;}}
.test-panel input:focus{{outline:none;border-color:var(--a2);}}
.test-result{{font-family:'Share Tech Mono',monospace;font-size:.6rem;color:var(--dim);margin:0 20px 6px;padding:4px 10px;}}
.test-result.ok{{color:var(--ok);}}.test-result.err{{color:var(--ng);}}
.log-toggle{{font-family:'Share Tech Mono',monospace;font-size:.58rem;padding:3px 8px;border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;transition:all .12s;}}
.log-toggle:hover{{border-color:var(--a2);color:var(--a2);}}.log-toggle.active{{border-color:var(--a2);color:var(--a2);}}
.log-area{{display:none;margin:0;padding:0;border-top:1px solid var(--border);}}.log-area.open{{display:block;}}
.log-inner{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1px;background:var(--border);}}
.log-node{{background:#0a0a0f;padding:6px 8px;min-height:80px;}}
.log-node-hd{{font-family:'Share Tech Mono',monospace;font-size:.58rem;color:var(--accent);margin-bottom:4px;display:flex;justify-content:space-between;align-items:center;}}
.log-node-hd .refresh-btn{{font-size:.5rem;padding:1px 5px;border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;}}
.log-node-hd .refresh-btn:hover{{border-color:var(--a2);color:var(--a2);}}
.log-text{{font-family:'Share Tech Mono',monospace;font-size:.52rem;color:#b0b0d0;white-space:pre-wrap;word-break:break-all;line-height:1.4;max-height:150px;overflow-y:auto;}}
</style></head><body>
<header><div><h1>&#9672; BI MONITOR</h1><div class="sub">スクリプト実行 (tmux) \u2014 SSH切断後も継続</div></div><nav>{nav}</nav></header>
<div class="toolbar">
  <button class="btn bp" onclick="runNums('run_start',allNums())">&#9654; START ALL</button>
  <button class="btn bd" onclick="if(confirm('\u5168\u30ce\u30fc\u30c9\u306e\u30b9\u30af\u30ea\u30d7\u30c8\u3092\u505c\u6b62\u3057\u307e\u3059\u304b?'))runNums('run_stop',allNums())">&#9632; STOP ALL</button>
  <button class="btn b2" onclick="runNums('run_check',allNums())">&#8635; CHECK ALL</button>
  <button class="btn" onclick="resetNums(allNums())">RESET</button>
  <div style="flex:1"></div><span class="btn" id="summary" style="cursor:default;border-color:transparent">\u2014</span>
</div>
<div class="test-panel"><label>SEND TEST:</label><label>NODE</label>
  <input type="number" id="testNum" value="1" min="1" max="100">
  <input type="text" id="testText" placeholder="\u30c6\u30ad\u30b9\u30c8\u3092\u5165\u529b..." value="\u68ee\u6797\u306e\u5965\u6df1\u304f\u306b\u306f">
  <button class="btn b2" onclick="sendTest()">SEND</button></div>
<div class="test-result" id="testResult"></div>
<div class="clusters" id="clusters"></div><div class="footer" id="footer"></div>
<script>
const PAGE='run';
const CL=Array.from({{length:10}},(_,i)=>({{s:i*10+1,e:i*10+10,l:`CLUSTER ${{String(i+1).padStart(2,'0')}} \u2014 NODE ${{i*10+1}}\u2013${{i*10+10}}`}}));
let J={{}};
function allNums(){{return Array.from({{length:100}},(_,i)=>i+1);}}
function clNums(ci){{const cl=CL[ci];return Array.from({{length:10}},(_,i)=>cl.s+i);}}
async function runNums(action,nums){{await fetch('/api/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action,page:PAGE,nums}})}});}}
async function resetNums(nums){{await fetch('/api/reset',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{page:PAGE,nums}})}});await poll();}}
async function sendTest(){{const num=document.getElementById('testNum').value;const text=document.getElementById('testText').value;const el=document.getElementById('testResult');el.className='test-result';el.textContent=`sending to NODE ${{num}} ...`;try{{const r=await fetch('/api/send_test',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{num,text}})}});const d=await r.json();if(d.ok){{el.className='test-result ok';el.textContent=`NODE ${{num}}: OK ${{d.stdout}}`;}}else{{el.className='test-result err';el.textContent=`NODE ${{num}}: ERR ${{d.stderr||d.stdout}}`;}}}}catch(e){{el.className='test-result err';el.textContent='Error: '+e;}}}}
function build(){{
  const c=document.getElementById('clusters');c.innerHTML='';
  CL.forEach((cl,ci)=>{{
    const d=document.createElement('div');d.className='cluster';
    d.innerHTML=`<div class="ch"><div class="ct">${{cl.l}}</div><div class="cs" id="cs${{ci}}">\u2014</div><div class="ca"><button class="cb" onclick="runNums('run_start',clNums(${{ci}}))">START</button><button class="cb" onclick="runNums('run_stop',clNums(${{ci}}))">STOP</button><button class="cb c2" onclick="runNums('run_check',clNums(${{ci}}))">CHECK</button><button class="cb c2" onclick="resetNums(clNums(${{ci}}))">RST</button><button class="log-toggle" id="lt${{ci}}" onclick="toggleLog(${{ci}})">LOG \u25bc</button></div></div><div class="grid" id="cg${{ci}}"></div><div class="log-area" id="la${{ci}}"><div class="log-inner" id="li${{ci}}"></div></div>`;
    c.appendChild(d);
    const g=document.getElementById('cg'+ci);
    for(let i=0;i<10;i++){{const n=cl.s+i;const nd=document.createElement('div');nd.className='node';nd.id='nd'+n;nd.title=`NODE ${{n}}`;nd.onclick=()=>nodeClick(n);nd.innerHTML=`<div class="nn">NODE ${{n}}</div><div class="dot"></div><div class="nl" id="nl${{n}}">\u2014</div>`;g.appendChild(nd);}}
    const li=document.getElementById('li'+ci);
    for(let i=0;i<10;i++){{const n=cl.s+i;const ld=document.createElement('div');ld.className='log-node';ld.id='ln'+n;ld.innerHTML=`<div class="log-node-hd"><span>NODE ${{n}} (10.0.0.${{n}})</span><button class="refresh-btn" onclick="event.stopPropagation();refreshLog(${{n}})">\u21bb</button></div><div class="log-text" id="logtext${{n}}">\u2014</div>`;li.appendChild(ld);}}
  }});
}}
function toggleLog(ci){{const la=document.getElementById('la'+ci);const lt=document.getElementById('lt'+ci);const isOpen=la.classList.toggle('open');lt.textContent=isOpen?'LOG \u25b2':'LOG \u25bc';lt.classList.toggle('active',isOpen);if(isOpen)fetchClusterLogs(ci);}}
async function fetchClusterLogs(ci){{const nums=clNums(ci);try{{const r=await fetch('/api/script_logs',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{nums}})}});const d=await r.json();for(const[n,log] of Object.entries(d)){{const el=document.getElementById('logtext'+n);if(el){{el.textContent=log||'(empty)';el.scrollTop=el.scrollHeight;}}}}}}catch(e){{}}}}
async function refreshLog(n){{try{{const r=await fetch('/api/script_log/'+n);const d=await r.json();const el=document.getElementById('logtext'+n);if(el){{el.textContent=d.log||'(empty)';el.scrollTop=el.scrollHeight;}}}}catch(e){{}}}}
async function nodeClick(n){{if(J[n]&&J[n].status==='running')return;await runNums('run_check',[n]);}}
function applyStatus(d){{J=d;let ok=0,ng=0,run=0,idle=0;for(let n=1;n<=100;n++){{const j=d[n]||{{status:'idle',msg:''}};const nd=document.getElementById('nd'+n),nl=document.getElementById('nl'+n);if(!nd)continue;nd.className='node st-'+j.status;nl.textContent=j.msg||j.status;if(j.status==='ok')ok++;else if(j.status==='error')ng++;else if(j.status==='running')run++;else idle++;}}document.getElementById('summary').textContent=`OK:${{ok}} ERR:${{ng}} RUN:${{run}} IDLE:${{idle}}`;CL.forEach((cl,ci)=>{{let co=0,cn=0,cr=0;for(let i=0;i<10;i++){{const j=d[cl.s+i];if(!j)continue;if(j.status==='ok')co++;else if(j.status==='error')cn++;else if(j.status==='running')cr++;}}const el=document.getElementById('cs'+ci);if(el){{el.textContent=`${{co}}ok/${{cn}}err/${{cr}}run`;el.style.color=co===10?'var(--ok)':cn>0?'var(--ng)':cr>0?'var(--run)':'var(--dim)';}}}});document.getElementById('footer').textContent='LAST: '+new Date().toLocaleTimeString();}}
async function poll(){{try{{const r=await fetch('/api/status/'+PAGE);applyStatus(await r.json())}}catch(e){{}}}}
async function autoRefreshLogs(){{for(let ci=0;ci<10;ci++){{const la=document.getElementById('la'+ci);if(la&&la.classList.contains('open'))await fetchClusterLogs(ci);}}}}
build();poll();setInterval(poll,2000);setInterval(autoRefreshLogs,5000);
</script></body></html>"""


# ── Static pages ─────────────────────────────────────────────────────────────
PAGES_HTML = {
    "led": make_html("led", "LED CHECK",
        "\u70b9\u706f\u78ba\u8a8d \u2014 \u30d5\u30a7\u30fc\u30c9\u30a2\u30c3\u30d7\u2192\u30d5\u30a7\u30fc\u30c9\u30c0\u30a6\u30f3\uff08\u5fc5\u305aOFF\u306b\u623b\u3057\u307e\u3059\uff09",
        '<button class="btn bp" onclick="runNums(\'led\',allNums())">&#9654; RUN ALL</button><button class="btn bd" onclick="resetNums(allNums())">RESET</button>',
        '[["led","","RUN"],["reset","c2","RST"]]',
        'async function cAct(ci,a){if(a==="reset")await resetNums(clNums(ci));else await runNums("led",clNums(ci));}\nasync function nodeClick(n){if(J[n]&&J[n].status==="running")return;await runNums("led",[n]);}'),
    "sound": make_html("sound", "SOUND CHECK",
        "\u30b5\u30a6\u30f3\u30c9\u30c1\u30a7\u30c3\u30af \u2014 tinyplay",
        '<button class="btn bp" onclick="runNums(\'sound\',allNums())">&#9654; RUN ALL</button><button class="btn bd" onclick="resetNums(allNums())">RESET</button>',
        '[["sound","","PLAY"],["reset","c2","RST"]]',
        'async function cAct(ci,a){if(a==="reset")await resetNums(clNums(ci));else await runNums("sound",clNums(ci));}\nasync function nodeClick(n){if(J[n]&&J[n].status==="running")return;await runNums("sound",[n]);}'),
}

@app.route("/")
def page_system(): return render_template_string(make_system_html())
@app.route("/led")
def page_led(): return render_template_string(PAGES_HTML["led"])
@app.route("/sound")
def page_sound(): return render_template_string(PAGES_HTML["sound"])
@app.route("/run")
def page_run(): return render_template_string(make_run_html())

if __name__ == "__main__":
    print("=" * 50)
    print("  BI MONITOR")
    print("  http://localhost:5050        -> 01 SYSTEM")
    print("  http://localhost:5050/led    -> 02 LED")
    print("  http://localhost:5050/sound  -> 03 SOUND")
    print("  http://localhost:5050/run    -> 04 RUN SCRIPTS")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
