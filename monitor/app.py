"""
BI MONITOR - 4ページ構成
  /        → Page 1: Ping チェック
  /system  → Page 2: インターネット確認 + git pull
  /led     → Page 3: LED 点灯チェック
  /sound   → Page 4: サウンドチェック

事前設定:
  SSH_USER = リモートホストのユーザー名
  GIT_DIR  = リモートのgitディレクトリ
  SSH鍵認証（パスワードなし）が必要
"""

from flask import Flask, jsonify, request, render_template_string
from pythonosc import udp_client
import threading, time, subprocess

app = Flask(__name__)

# ── 設定 ──────────────────────────────────────────────────────────────────────
NODE_PREFIX = "10.0.0"
NODE_COUNT  = 100
OSC_PORT    = 9000
SSH_USER    = "pi"           # ← 変更してください
GIT_DIR     = "~/project"    # ← 変更してください
SOUND_CMD   = "tinyplay -D0 -d1 /usr/local/m5stack/logo.wav"
LED_STEPS   = 40
LED_UP_SEC  = 2.0
LED_DN_SEC  = 2.0

# ── ジョブ管理 ─────────────────────────────────────────────────────────────────
PAGES = ["ping", "system", "led", "sound"]
jobs = {p: {n: {"status": "idle", "msg": ""} for n in range(1, NODE_COUNT+1)} for p in PAGES}
job_locks = {p: {n: threading.Lock() for n in range(1, NODE_COUNT+1)} for p in PAGES}

def set_job(page, num, status, msg=""):
    jobs[page][num] = {"status": status, "msg": msg}

def is_running(page, num):
    return jobs[page][num]["status"] == "running"

def node_ip(num):
    return f"{NODE_PREFIX}.{num}"

# ── ユーティリティ ─────────────────────────────────────────────────────────────
def ping_ip(ip):
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "1", ip],
                           capture_output=True, text=True, timeout=2)
        if r.returncode == 0:
            for line in r.stdout.split("\n"):
                if "time=" in line:
                    lat = line.split("time=")[1].split(" ")[0]
                    return True, f"{lat}ms"
            return True, "ok"
        return False, "offline"
    except:
        return False, "error"

def ssh_run(ip, cmd, timeout=15):
    r = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=5", "-o", "BatchMode=yes",
         f"{SSH_USER}@{ip}", cmd],
        capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

# ── Page 1: Ping ──────────────────────────────────────────────────────────────
def _ping_worker(num):
    page = "ping"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running")
        alive, lat = ping_ip(node_ip(num))
        set_job(page, num, "ok" if alive else "error", lat)
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        job_locks[page][num].release()

def bg_ping_loop():
    while True:
        threads = [threading.Thread(target=_ping_worker, args=(n,), daemon=True)
                   for n in range(1, NODE_COUNT+1) if not is_running("ping", n)]
        for t in threads: t.start()
        for t in threads: t.join()
        time.sleep(15)

threading.Thread(target=bg_ping_loop, daemon=True).start()

# ── Page 2: Internet check ────────────────────────────────────────────────────
def _internet_worker(num):
    page = "system"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "checking...")
        code, out, err = ssh_run(node_ip(num), "ping -c 1 -W 2 8.8.8.8 && echo OK", timeout=10)
        if code == 0:
            set_job(page, num, "ok", "inet ok")
        else:
            set_job(page, num, "error", "no internet")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "ssh timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        job_locks[page][num].release()

# ── Page 2: Git pull ──────────────────────────────────────────────────────────
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

# ── Page 3: LED check ─────────────────────────────────────────────────────────
def _led_worker(num):
    """フェードアップ→フェードダウン。例外時も必ずLED=0.0を送信する。"""
    page = "led"
    ip = node_ip(num)
    if not job_locks[page][num].acquire(blocking=False): return
    dt_up = LED_UP_SEC / LED_STEPS
    dt_dn = LED_DN_SEC / LED_STEPS
    try:
        set_job(page, num, "running", "fade up...")
        client = udp_client.SimpleUDPClient(ip, OSC_PORT)
        # フェードアップ 0 → 1
        for i in range(LED_STEPS + 1):
            client.send_message("/led", float(i / LED_STEPS))
            time.sleep(dt_up)
        set_job(page, num, "running", "fade down...")
        # フェードダウン 1 → 0
        for i in range(LED_STEPS, -1, -1):
            client.send_message("/led", float(i / LED_STEPS))
            time.sleep(dt_dn)
        # 念押し 0 を送信
        client.send_message("/led", 0.0)
        set_job(page, num, "ok", "done / off")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        # ★ どんな例外が起きても必ずOFFにする
        try:
            udp_client.SimpleUDPClient(ip, OSC_PORT).send_message("/led", 0.0)
        except Exception:
            pass
        job_locks[page][num].release()

# ── Page 4: Sound check ───────────────────────────────────────────────────────
def _sound_worker(num):
    page = "sound"
    if not job_locks[page][num].acquire(blocking=False): return
    try:
        set_job(page, num, "running", "playing...")
        code, out, err = ssh_run(node_ip(num), SOUND_CMD, timeout=20)
        if code == 0:
            set_job(page, num, "ok", "played")
        else:
            set_job(page, num, "error", (err or out)[:24] or "error")
    except subprocess.TimeoutExpired:
        set_job(page, num, "error", "timeout")
    except Exception as e:
        set_job(page, num, "error", str(e)[:20])
    finally:
        job_locks[page][num].release()

WORKERS = {
    "ping": _ping_worker, "inet": _internet_worker,
    "gitpull": _gitpull_worker, "led": _led_worker, "sound": _sound_worker,
}

def run_worker(action, num):
    fn = WORKERS.get(action)
    if fn:
        threading.Thread(target=fn, args=(num,), daemon=True).start()

# ── API ───────────────────────────────────────────────────────────────────────
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
        if not is_running(page, n):
            set_job(page, n, "idle", "")
    return jsonify({"ok": True})

# ── HTML テンプレート（共通） ─────────────────────────────────────────────────
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
.node.st-ok{background:#071410;}
.node.st-error{background:#140707;}
.node.st-running{background:#07100d;}
.nn{font-family:'Share Tech Mono',monospace;font-size:.58rem;color:var(--dim);}
.dot{width:8px;height:8px;border-radius:50%;background:var(--dim);transition:all .3s;margin:2px 0;}
.st-ok .dot{background:var(--ok);box-shadow:0 0 5px rgba(64,240,128,.5);}
.st-error .dot{background:var(--ng);}
.st-running .dot{background:var(--run);animation:blink .7s ease-in-out infinite;}
@keyframes blink{0%,100%{opacity:.2}50%{opacity:1}}
.nl{font-family:'Share Tech Mono',monospace;font-size:.5rem;color:var(--dim);text-align:center;word-break:break-all;line-height:1.3;}
.st-ok .nl{color:var(--ok);}
.st-error .nl{color:var(--ng);}
.st-running .nl{color:var(--run);}
.footer{font-family:'Share Tech Mono',monospace;font-size:.6rem;color:var(--dim);padding:6px 20px 12px;}
"""

def make_html(page_id, title, subtitle, toolbar_html, cluster_btn_defs, js_actions):
    nav = ""
    tabs = [("/","ping","01 PING"),("/system","system","02 SYSTEM"),("/led","led","03 LED"),("/sound","sound","04 SOUND")]
    for url, pid, label in tabs:
        active = ' class="nt on"' if pid == page_id else ' class="nt"'
        nav += f'<a href="{url}"{active}>{label}</a>'

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>BI MONITOR — {title}</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;500;700&display=swap" rel="stylesheet">
<style>{SHARED_CSS}</style>
</head>
<body>
<header>
  <div><h1>&#9672; BI MONITOR</h1><div class="sub">{subtitle}</div></div>
  <nav>{nav}</nav>
</header>
<div class="toolbar">{toolbar_html}<div style="flex:1"></div><span class="btn" id="summary" style="cursor:default;border-color:transparent">—</span></div>
<div class="clusters" id="clusters"></div>
<div class="footer" id="footer"></div>
<script>
const PAGE='{page_id}';
const CL=Array.from({{length:10}},(_,i)=>({{s:i*10+1,e:i*10+10,l:`CLUSTER ${{String(i+1).padStart(2,'0')}} \u2014 NODE ${{i*10+1}}\u2013${{i*10+10}}`}}));
const CBTNS={cluster_btn_defs};
let J={{}};

function build(){{
  const c=document.getElementById('clusters');c.innerHTML='';
  CL.forEach((cl,ci)=>{{
    const d=document.createElement('div');d.className='cluster';
    const ca=CBTNS.map(([a,cls,l])=>`<button class="cb ${{cls}}" onclick="cAct(${{ci}},'${{a}}')">${{l}}</button>`).join('');
    d.innerHTML=`<div class="ch"><div class="ct">${{cl.l}}</div><div class="cs" id="cs${{ci}}">—</div><div class="ca">${{ca}}</div></div><div class="grid" id="cg${{ci}}"></div>`;
    c.appendChild(d);
    const g=document.getElementById('cg'+ci);
    for(let i=0;i<10;i++){{
      const n=cl.s+i;
      const nd=document.createElement('div');
      nd.className='node';nd.id='nd'+n;nd.title=`NODE ${{n}} (10.0.0.${{n}}) — クリックで個別実行`;
      nd.onclick=()=>nodeClick(n);
      nd.innerHTML=`<div class="nn">NODE ${{n}}</div><div class="dot"></div><div class="nl" id="nl${{n}}">—</div>`;
      g.appendChild(nd);
    }}
  }});
}}

function applyStatus(d){{
  J=d;let ok=0,ng=0,run=0,idle=0;
  for(let n=1;n<=100;n++){{
    const j=d[n]||{{status:'idle',msg:''}};
    const nd=document.getElementById('nd'+n),nl=document.getElementById('nl'+n);
    if(!nd)continue;
    nd.className='node st-'+j.status;
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

async function runNums(action,nums){{await fetch('/api/run',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{action,page:PAGE,nums}})}});}}
async function resetNums(nums){{await fetch('/api/reset',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{page:PAGE,nums}})}});await poll();}}

function allNums(){{return Array.from({{length:100}},(_,i)=>i+1);}}
function clNums(ci){{const cl=CL[ci];return Array.from({{length:10}},(_,i)=>cl.s+i);}}

{js_actions}

build();poll();setInterval(poll,1500);
</script>
</body>
</html>"""


# ── 各ページのHTML ────────────────────────────────────────────────────────────
PAGES_HTML = {
    "ping": make_html(
        "ping", "PING CHECK", "疎通確認 — 15秒ごと自動更新",
        '<button class="btn bp" onclick="runNums(\'ping\',allNums())">&#9654; RUN ALL</button>'
        '<button class="btn bd" onclick="resetNums(allNums())">RESET</button>',
        '[["ping","","RUN"],["reset","c2","RST"]]',
        """
async function cAct(ci,a){if(a==='reset')await resetNums(clNums(ci));else await runNums('ping',clNums(ci));}
async function nodeClick(n){if(J[n]&&J[n].status==='running')return;await runNums('ping',[n]);}
"""
    ),
    "system": make_html(
        "system", "SYSTEM CHECK", "インターネット確認 / git pull",
        '<button class="btn b2" onclick="runNums(\'inet\',allNums())">&#9654; INET ALL</button>'
        '<button class="btn bp" onclick="runNums(\'gitpull\',allNums())">&#9654; GIT PULL ALL</button>'
        '<button class="btn bd" onclick="resetNums(allNums())">RESET</button>',
        '[["inet","c2","INET"],["gitpull","","GIT"],["reset","","RST"]]',
        """
async function cAct(ci,a){
  if(a==='reset')await resetNums(clNums(ci));
  else if(a==='inet')await runNums('inet',clNums(ci));
  else if(a==='gitpull')await runNums('gitpull',clNums(ci));
}
async function nodeClick(n){if(J[n]&&J[n].status==='running')return;await runNums('inet',[n]);}
"""
    ),
    "led": make_html(
        "led", "LED CHECK", "点灯確認 — フェードアップ→フェードダウン（必ずOFFに戻します）",
        '<button class="btn bp" onclick="runNums(\'led\',allNums())">&#9654; RUN ALL</button>'
        '<button class="btn bd" onclick="resetNums(allNums())">RESET</button>',
        '[["led","","RUN"],["reset","c2","RST"]]',
        """
async function cAct(ci,a){if(a==='reset')await resetNums(clNums(ci));else await runNums('led',clNums(ci));}
async function nodeClick(n){if(J[n]&&J[n].status==='running')return;await runNums('led',[n]);}
"""
    ),
    "sound": make_html(
        "sound", "SOUND CHECK", "サウンドチェック — tinyplay",
        '<button class="btn bp" onclick="runNums(\'sound\',allNums())">&#9654; RUN ALL</button>'
        '<button class="btn bd" onclick="resetNums(allNums())">RESET</button>',
        '[["sound","","PLAY"],["reset","c2","RST"]]',
        """
async function cAct(ci,a){if(a==='reset')await resetNums(clNums(ci));else await runNums('sound',clNums(ci));}
async function nodeClick(n){if(J[n]&&J[n].status==='running')return;await runNums('sound',[n]);}
"""
    ),
}

@app.route("/")
def page_ping(): return render_template_string(PAGES_HTML["ping"])

@app.route("/system")
def page_system(): return render_template_string(PAGES_HTML["system"])

@app.route("/led")
def page_led(): return render_template_string(PAGES_HTML["led"])

@app.route("/sound")
def page_sound(): return render_template_string(PAGES_HTML["sound"])


if __name__ == "__main__":
    print("=" * 50)
    print("  BI MONITOR")
    print("  http://localhost:5050        → 01 PING")
    print("  http://localhost:5050/system → 02 SYSTEM")
    print("  http://localhost:5050/led    → 03 LED")
    print("  http://localhost:5050/sound  → 04 SOUND")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
