from flask import Flask, render_template_string, request, jsonify
from pythonosc import udp_client
import threading, time, json, os, subprocess

app = Flask(__name__)
hosts = {}
hosts_lock = threading.Lock()
fade_threads = {}
ping_status = {}
DATA_FILE = "hosts.json"

def load_hosts():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE) as f:
            return json.load(f)
    return {}

def save_hosts():
    with open(DATA_FILE, "w") as f:
        json.dump(hosts, f, indent=2)

def send_osc(ip, port, value):
    try:
        client = udp_client.SimpleUDPClient(ip, int(port))
        client.send_message("/led", float(value))
        return True
    except Exception as e:
        print(f"OSC Error {ip}:{port} -> {e}")
        return False

def fade_worker(host_id, start_val, end_val, duration, steps=40):
    dt = duration / steps
    for i in range(steps + 1):
        if fade_threads.get(host_id) != threading.current_thread():
            return
        v = start_val + (end_val - start_val) * (i / steps)
        with hosts_lock:
            h = hosts.get(host_id)
            if not h:
                return
            h["value"] = round(v, 4)
        send_osc(h["ip"], h["port"], v)
        time.sleep(dt)

def ping_ip(ip):
    try:
        result = subprocess.run(["ping", "-c", "1", "-W", "1", ip],
            capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "time=" in line:
                    latency = line.split("time=")[1].split(" ")[0]
                    return True, f"{latency}ms"
            return True, "-"
        return False, "-"
    except:
        return False, "-"

def ping_worker():
    while True:
        ips = [f"10.0.0.{i}" for i in range(1, 101)]
        def check(ip):
            alive, lat = ping_ip(ip)
            ping_status[ip] = {"alive": alive, "latency": lat, "last": time.time()}
        threads = [threading.Thread(target=check, args=(ip,), daemon=True) for ip in ips]
        for t in threads: t.start()
        for t in threads: t.join()
        time.sleep(15)

threading.Thread(target=ping_worker, daemon=True).start()

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)

@app.route("/ping")
def ping_page():
    return render_template_string(PING_HTML)

@app.route("/api/hosts", methods=["GET"])
def get_hosts():
    with hosts_lock:
        return jsonify(hosts)

@app.route("/api/hosts", methods=["POST"])
def add_host():
    data = request.json
    host_id = data.get("id") or str(int(time.time() * 1000))
    with hosts_lock:
        hosts[host_id] = {
            "id": host_id, "name": data.get("name", "Light"),
            "ip": data["ip"], "port": int(data.get("port", 9000)),
            "value": 0.0, "fade_up": float(data.get("fade_up", 2.0)),
            "fade_down": float(data.get("fade_down", 2.0)),
        }
        save_hosts()
    return jsonify({"ok": True, "id": host_id})

@app.route("/api/hosts/<host_id>", methods=["DELETE"])
def delete_host(host_id):
    with hosts_lock:
        hosts.pop(host_id, None)
        save_hosts()
    return jsonify({"ok": True})

@app.route("/api/hosts/<host_id>", methods=["PATCH"])
def update_host(host_id):
    data = request.json
    with hosts_lock:
        h = hosts.get(host_id)
        if not h:
            return jsonify({"error": "not found"}), 404
        for k in ["name", "ip", "port", "fade_up", "fade_down"]:
            if k in data:
                h[k] = data[k]
        save_hosts()
    return jsonify({"ok": True})

@app.route("/api/send/<host_id>", methods=["POST"])
def send_value(host_id):
    data = request.json
    value = float(data.get("value", 0))
    with hosts_lock:
        h = hosts.get(host_id)
        if not h:
            return jsonify({"error": "not found"}), 404
        h["value"] = value
    ok = send_osc(h["ip"], h["port"], value)
    return jsonify({"ok": ok})

@app.route("/api/fade/<host_id>", methods=["POST"])
def fade_host(host_id):
    data = request.json
    direction = data.get("direction", "up")
    with hosts_lock:
        h = hosts.get(host_id)
        if not h:
            return jsonify({"error": "not found"}), 404
        start = h["value"]
        end = 1.0 if direction == "up" else 0.0
        duration = h["fade_up"] if direction == "up" else h["fade_down"]
    t = threading.Thread(target=fade_worker, args=(host_id, start, end, duration), daemon=True)
    fade_threads[host_id] = t
    t.start()
    return jsonify({"ok": True})

@app.route("/api/all", methods=["POST"])
def all_action():
    data = request.json
    action = data.get("action")
    with hosts_lock:
        ids = list(hosts.keys())
    for host_id in ids:
        with hosts_lock:
            h = hosts.get(host_id)
        if not h:
            continue
        if action in ("on", "off"):
            val = 1.0 if action == "on" else 0.0
            with hosts_lock:
                h["value"] = val
            send_osc(h["ip"], h["port"], val)
        elif action in ("fade_up", "fade_down"):
            direction = "up" if action == "fade_up" else "down"
            start = h["value"]
            end = 1.0 if direction == "up" else 0.0
            duration = h["fade_up"] if direction == "up" else h["fade_down"]
            t = threading.Thread(target=fade_worker, args=(host_id, start, end, duration), daemon=True)
            fade_threads[host_id] = t
            t.start()
    return jsonify({"ok": True})

@app.route("/api/ping_status")
def get_ping_status():
    return jsonify(ping_status)

@app.route("/api/ping_now", methods=["POST"])
def ping_now():
    data = request.json
    ip = data.get("ip")
    if ip:
        alive, lat = ping_ip(ip)
        ping_status[ip] = {"alive": alive, "latency": lat, "last": time.time()}
        return jsonify(ping_status[ip])
    return jsonify({"error": "no ip"}), 400

INDEX_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BI MONITOR</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;500;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0a0f;--panel:#111118;--border:#1e1e2e;--accent:#f0c040;--accent2:#40c0f0;--dim:#444460;--text:#cccce0;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:'Barlow',sans-serif;min-height:100vh;}
header{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;border-bottom:1px solid var(--border);background:var(--panel);}
header h1{font-family:'Share Tech Mono',monospace;font-size:1.1rem;color:var(--accent);letter-spacing:4px;}
.status-bar{font-family:'Share Tech Mono',monospace;font-size:.72rem;color:var(--dim);margin-top:2px;}
.nav-link{font-family:'Share Tech Mono',monospace;font-size:.72rem;color:var(--accent2);text-decoration:none;border:1px solid var(--accent2);padding:5px 12px;}
.nav-link:hover{background:rgba(64,192,240,.08);}
.global-bar{display:flex;gap:10px;padding:12px 24px;background:#0d0d14;border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:center;}
.global-bar label{font-size:.75rem;color:var(--dim);letter-spacing:2px;}
.btn{font-family:'Share Tech Mono',monospace;font-size:.75rem;padding:6px 14px;border:1px solid var(--dim);background:transparent;color:var(--text);cursor:pointer;letter-spacing:1px;transition:all .15s;}
.btn:hover{border-color:var(--accent);color:var(--accent);}
.btn.primary{border-color:var(--accent);color:var(--accent);}
.btn.accent2{border-color:var(--accent2);color:var(--accent2);}
.clusters{padding:16px 24px;display:flex;flex-direction:column;gap:12px;}
.cluster{border:1px solid var(--border);}
.cluster-header{display:flex;align-items:center;gap:12px;padding:8px 14px;background:#0d0d14;border-bottom:1px solid var(--border);flex-wrap:wrap;}
.cluster-title{font-family:'Share Tech Mono',monospace;font-size:.78rem;color:var(--accent);letter-spacing:2px;}
.cluster-count{font-family:'Share Tech Mono',monospace;font-size:.65rem;color:var(--dim);}
.cluster-actions{margin-left:auto;display:flex;gap:6px;}
.cbtn{font-family:'Share Tech Mono',monospace;font-size:.62rem;padding:4px 10px;border:1px solid var(--border);background:transparent;color:var(--dim);cursor:pointer;transition:all .12s;}
.cbtn:hover{border-color:var(--accent);color:var(--accent);}
.cbtn.c2:hover{border-color:var(--accent2);color:var(--accent2);}
.cards{display:grid;grid-template-columns:repeat(10,1fr);gap:1px;background:var(--border);padding:1px;}
.card{background:#0e0e16;padding:10px 6px;display:flex;flex-direction:column;gap:5px;}
.card.active{background:#151510;}
.card-num{font-family:'Share Tech Mono',monospace;font-size:.62rem;color:var(--dim);text-align:center;}
.card-ip{font-family:'Share Tech Mono',monospace;font-size:.55rem;color:#2a2a3a;text-align:center;}
.val-disp{font-family:'Share Tech Mono',monospace;font-size:1.05rem;color:var(--dim);text-align:center;transition:color .2s;}
.val-disp.on{color:var(--accent);}
input[type=range]{width:100%;height:3px;appearance:none;background:linear-gradient(to right,var(--accent) var(--pct,0%),#1a1a28 var(--pct,0%));border-radius:2px;outline:none;cursor:pointer;}
input[type=range]::-webkit-slider-thumb{appearance:none;width:10px;height:10px;background:var(--accent);border-radius:50%;}
.fade-row{display:flex;gap:3px;}
.fc{flex:1;font-family:'Share Tech Mono',monospace;font-size:.55rem;padding:3px 0;border:1px solid #1a1a28;background:transparent;color:#2a2a3a;cursor:pointer;transition:all .12s;}
.fc:hover{border-color:var(--accent2);color:var(--accent2);}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:100;align-items:center;justify-content:center;}
.modal-bg.show{display:flex;}
.modal{background:var(--panel);border:1px solid var(--accent);padding:28px;width:360px;max-width:95vw;}
.modal h2{font-family:'Share Tech Mono',monospace;font-size:.9rem;color:var(--accent);margin-bottom:20px;letter-spacing:3px;}
.field{margin-bottom:14px;}
.field label{display:block;font-size:.7rem;color:var(--dim);letter-spacing:2px;margin-bottom:5px;}
.field input{width:100%;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:8px 10px;font-family:'Share Tech Mono',monospace;font-size:.85rem;outline:none;}
.field input:focus{border-color:var(--accent);}
.modal-actions{display:flex;gap:10px;margin-top:20px;}
.num-inp{background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px;font-family:'Share Tech Mono',monospace;font-size:.8rem;}
</style>
</head>
<body>
<header>
  <div>
    <h1>&#9672; BI MONITOR</h1>
    <div class="status-bar" id="statusBar">HOSTS: 0 / ACTIVE: 0</div>
  </div>
  <div style="display:flex;gap:12px;align-items:center">
    <a href="/ping" class="nav-link">&#9677; PING STATUS</a>
    <button class="btn primary" onclick="openModal()">+ ADD HOST</button>
  </div>
</header>
<div class="global-bar">
  <label>ALL:</label>
  <button class="btn primary" onclick="allAction('on')">ALL ON</button>
  <button class="btn" onclick="allAction('off')">ALL OFF</button>
  <button class="btn accent2" onclick="allAction('fade_up')">FADE UP ALL</button>
  <button class="btn" onclick="allAction('fade_down')">FADE DOWN ALL</button>
  <div style="flex:1"></div>
  <label>FADE UP</label>
  <input type="number" id="gFadeUp" value="2" step="0.1" min="0.1" class="num-inp" style="width:55px">
  <label>DOWN</label>
  <input type="number" id="gFadeDown" value="2" step="0.1" min="0.1" class="num-inp" style="width:55px">
  <button class="btn" onclick="applyGlobalFade()">APPLY</button>
</div>
<div class="clusters" id="clusters"></div>
<div class="modal-bg" id="addModal">
  <div class="modal">
    <h2>ADD HOST</h2>
    <div class="field"><label>NAME</label><input id="f_name" placeholder="Light 1"></div>
    <div class="field"><label>IP ADDRESS</label><input id="f_ip" placeholder="10.0.0.1"></div>
    <div class="field"><label>PORT</label><input id="f_port" value="9000"></div>
    <div class="field"><label>FADE UP (sec)</label><input id="f_fup" value="2" type="number" step="0.1"></div>
    <div class="field"><label>FADE DOWN (sec)</label><input id="f_fdn" value="2" type="number" step="0.1"></div>
    <div class="modal-actions">
      <button class="btn primary" onclick="addHost()">ADD</button>
      <button class="btn" onclick="closeModal()">CANCEL</button>
    </div>
  </div>
</div>
<script>
let hosts={};
const CLUSTERS=Array.from({length:10},(_,i)=>({start:i*10+1,end:i*10+10,label:`CLUSTER ${String(i+1).padStart(2,'0')} \u2014 NODE ${i*10+1}\u2013${i*10+10}`}));
async function loadHosts(){const r=await fetch('/api/hosts');hosts=await r.json();renderClusters();}
function renderClusters(){
  const container=document.getElementById('clusters');container.innerHTML='';
  CLUSTERS.forEach((cl,ci)=>{
    const active=Array.from({length:10},(_,i)=>{const h=Object.values(hosts).find(h=>h.ip===`10.0.0.${cl.start+i}`);return h&&h.value>0.01;}).filter(Boolean).length;
    const div=document.createElement('div');div.className='cluster';
    div.innerHTML=`<div class="cluster-header"><div class="cluster-title">${cl.label}</div><div class="cluster-count" id="cl-cnt-${ci}">${active}/10 ACTIVE</div><div class="cluster-actions"><button class="cbtn" onclick="clusterAction(${ci},'on')">ON</button><button class="cbtn" onclick="clusterAction(${ci},'off')">OFF</button><button class="cbtn c2" onclick="clusterAction(${ci},'fade_up')">&#9650; FADE</button><button class="cbtn c2" onclick="clusterAction(${ci},'fade_down')">&#9660; FADE</button></div></div><div class="cards" id="cl-cards-${ci}"></div>`;
    container.appendChild(div);
    const cardsEl=document.getElementById(`cl-cards-${ci}`);
    for(let i=0;i<10;i++){
      const num=cl.start+i,ip=`10.0.0.${num}`;
      const h=Object.values(hosts).find(h=>h.ip===ip);
      const val=h?h.value:0,pct=(val*100).toFixed(0),isOn=val>0.01;
      const card=document.createElement('div');card.className=`card${isOn?' active':''}`;card.id=`card-${num}`;
      card.innerHTML=`<div class="card-num">NODE ${num}</div><div class="card-ip">.${num}</div><div class="val-disp ${isOn?'on':''}" id="val-${num}">${val.toFixed(2)}</div><input type="range" min="0" max="1" step="0.01" value="${val}" style="--pct:${pct}%" data-ip="${ip}" data-num="${num}" oninput="onSlider(this)" onchange="sendByIp('${ip}',parseFloat(this.value))"><div class="fade-row"><button class="fc" onclick="fadeByIp('${ip}','up')">&#9650;</button><button class="fc" onclick="fadeByIp('${ip}','down')">&#9660;</button></div>`;
      cardsEl.appendChild(card);
    }
  });
  updateStatus();
}
function onSlider(el){const v=parseFloat(el.value),num=el.dataset.num;el.style.setProperty('--pct',(v*100).toFixed(0)+'%');const vEl=document.getElementById(`val-${num}`);if(vEl){vEl.textContent=v.toFixed(2);vEl.className=`val-disp ${v>0.01?'on':''}`;}const card=document.getElementById(`card-${num}`);if(card)card.className=`card${v>0.01?' active':''}`;const h=Object.values(hosts).find(h=>h.ip===el.dataset.ip);if(h)h.value=v;}
async function sendByIp(ip,value){const h=Object.values(hosts).find(h=>h.ip===ip);if(h)await fetch(`/api/send/${h.id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({value})});updateStatus();}
async function fadeByIp(ip,direction){const h=Object.values(hosts).find(h=>h.ip===ip);if(!h)return;await fetch(`/api/fade/${h.id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({direction})});pollFadeByIp(ip);}
function pollFadeByIp(ip){let count=0;const num=parseInt(ip.split('.')[3]);const iv=setInterval(async()=>{const r=await fetch('/api/hosts');const all=await r.json();const h=Object.values(all).find(h=>h.ip===ip);if(h){hosts[h.id]=h;const v=h.value;const slider=document.querySelector(`input[data-ip="${ip}"]`);if(slider){slider.value=v;slider.style.setProperty('--pct',(v*100).toFixed(0)+'%');}const vEl=document.getElementById(`val-${num}`);if(vEl){vEl.textContent=v.toFixed(2);vEl.className=`val-disp ${v>0.01?'on':''}`;}const card=document.getElementById(`card-${num}`);if(card)card.className=`card${v>0.01?' active':''}`;}if(++count>150)clearInterval(iv);updateStatus();},200);}
async function clusterAction(ci,action){const cl=CLUSTERS[ci];for(let i=0;i<10;i++){const ip=`10.0.0.${cl.start+i}`;const h=Object.values(hosts).find(h=>h.ip===ip);if(!h)continue;if(action==='on'||action==='off'){const val=action==='on'?1.0:0.0;await fetch(`/api/send/${h.id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({value:val})});h.value=val;}else{const dir=action==='fade_up'?'up':'down';await fetch(`/api/fade/${h.id}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({direction:dir})});pollFadeByIp(ip);}}if(action==='on'||action==='off')renderClusters();}
async function allAction(action){await fetch('/api/all',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});if(action.includes('fade'))Object.values(hosts).forEach(h=>pollFadeByIp(h.ip));else await loadHosts();}
async function applyGlobalFade(){const up=parseFloat(document.getElementById('gFadeUp').value),dn=parseFloat(document.getElementById('gFadeDown').value);for(const id of Object.keys(hosts))await fetch(`/api/hosts/${id}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({fade_up:up,fade_down:dn})});await loadHosts();}
function updateStatus(){const total=Object.keys(hosts).length,active=Object.values(hosts).filter(h=>h.value>0.01).length;document.getElementById('statusBar').textContent=`HOSTS: ${total} / ACTIVE: ${active}`;}
function openModal(){document.getElementById('addModal').classList.add('show');}
function closeModal(){document.getElementById('addModal').classList.remove('show');}
async function addHost(){const data={name:document.getElementById('f_name').value||'Light',ip:document.getElementById('f_ip').value,port:parseInt(document.getElementById('f_port').value)||9000,fade_up:parseFloat(document.getElementById('f_fup').value)||2,fade_down:parseFloat(document.getElementById('f_fdn').value)||2};if(!data.ip)return;await fetch('/api/hosts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});closeModal();await loadHosts();}
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
loadHosts();
</script>
</body>
</html>"""

PING_HTML = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>BI MONITOR — PING</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;500;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#0a0a0f;--panel:#111118;--border:#1e1e2e;--accent:#f0c040;--accent2:#40c0f0;--dim:#444460;--text:#cccce0;--ok:#40f080;--ng:#f04040;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:'Barlow',sans-serif;min-height:100vh;}
header{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;border-bottom:1px solid var(--border);background:var(--panel);}
header h1{font-family:'Share Tech Mono',monospace;font-size:1.1rem;color:var(--accent);letter-spacing:4px;}
.nav-link{font-family:'Share Tech Mono',monospace;font-size:.72rem;color:var(--accent2);text-decoration:none;border:1px solid var(--accent2);padding:5px 12px;}
.nav-link:hover{background:rgba(64,192,240,.08);}
.toolbar{display:flex;gap:12px;align-items:center;padding:12px 24px;background:#0d0d14;border-bottom:1px solid var(--border);flex-wrap:wrap;}
.stat{font-family:'Share Tech Mono',monospace;font-size:.72rem;}
.stat .ok{color:var(--ok);}  .stat .ng{color:var(--ng);}  .stat .dim{color:var(--dim);}
.btn{font-family:'Share Tech Mono',monospace;font-size:.75rem;padding:6px 14px;border:1px solid var(--dim);background:transparent;color:var(--text);cursor:pointer;transition:all .15s;}
.btn:hover{border-color:var(--accent);color:var(--accent);}
.clusters{padding:16px 24px;display:flex;flex-direction:column;gap:12px;}
.cluster{border:1px solid var(--border);}
.cluster-header{display:flex;align-items:center;gap:12px;padding:7px 14px;background:#0d0d14;border-bottom:1px solid var(--border);}
.cluster-title{font-family:'Share Tech Mono',monospace;font-size:.78rem;color:var(--accent);letter-spacing:2px;}
.cluster-ok{font-family:'Share Tech Mono',monospace;font-size:.65rem;margin-left:auto;}
.ping-grid{display:grid;grid-template-columns:repeat(10,1fr);gap:1px;background:var(--border);padding:1px;}
.ping-cell{background:var(--bg);padding:10px 6px;text-align:center;display:flex;flex-direction:column;gap:4px;align-items:center;cursor:pointer;transition:background .15s;}
.ping-cell:hover{background:#111120;}
.ping-cell.alive{background:#071410;}
.ping-cell.dead{background:#140707;}
.dot{width:10px;height:10px;border-radius:50%;background:var(--dim);transition:background .3s;}
.alive .dot{background:var(--ok);box-shadow:0 0 6px rgba(64,240,128,.5);}
.dead .dot{background:var(--ng);}
.pending .dot{animation:pulse 1s ease-in-out infinite;}
@keyframes pulse{0%,100%{opacity:.3}50%{opacity:1}}
.ping-num{font-family:'Share Tech Mono',monospace;font-size:.62rem;color:var(--dim);}
.ping-label{font-family:'Share Tech Mono',monospace;font-size:.6rem;color:var(--dim);}
.alive .ping-label{color:var(--ok);}  .dead .ping-label{color:var(--ng);}
.ping-lat{font-family:'Share Tech Mono',monospace;font-size:.55rem;color:#303048;}
.alive .ping-lat{color:#306040;}
.last-update{font-family:'Share Tech Mono',monospace;font-size:.65rem;color:var(--dim);padding:8px 24px;}
.spin{animation:spin 1s linear infinite;display:inline-block;}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
</style>
</head>
<body>
<header>
  <div><h1>&#9672; BI MONITOR &#8212; PING STATUS</h1></div>
  <div style="display:flex;gap:12px;align-items:center">
    <button class="btn" id="refreshBtn" onclick="refreshAll()">&#8635; REFRESH ALL</button>
    <a href="/" class="nav-link">&#8592; CONTROLLER</a>
  </div>
</header>
<div class="toolbar">
  <div class="stat">ONLINE: <span class="ok" id="cntOk">-</span></div>
  <div class="stat">OFFLINE: <span class="ng" id="cntNg">-</span></div>
  <div class="stat">PENDING: <span class="dim" id="cntPend">-</span></div>
  <div style="flex:1"></div>
  <div class="stat dim">AUTO REFRESH: 15s</div>
</div>
<div class="clusters" id="clusters"></div>
<div class="last-update" id="lastUpdate"></div>
<script>
const CLUSTERS=Array.from({length:10},(_,i)=>({start:i*10+1,end:i*10+10,label:`CLUSTER ${String(i+1).padStart(2,'0')} \u2014 NODE ${i*10+1}\u2013${i*10+10}`}));
let pingData={};
function buildGrid(){
  const container=document.getElementById('clusters');container.innerHTML='';
  CLUSTERS.forEach((cl,ci)=>{
    const div=document.createElement('div');div.className='cluster';
    div.innerHTML=`<div class="cluster-header"><div class="cluster-title">${cl.label}</div><div class="cluster-ok" id="cl-stat-${ci}">- / 10</div></div><div class="ping-grid" id="cl-grid-${ci}"></div>`;
    container.appendChild(div);
    const grid=document.getElementById(`cl-grid-${ci}`);
    for(let i=0;i<10;i++){
      const num=cl.start+i,ip=`10.0.0.${num}`;
      const cell=document.createElement('div');cell.className='ping-cell pending';cell.id=`cell-${num}`;cell.title=`クリックで個別ping: ${ip}`;cell.onclick=()=>pingOne(ip,num);
      cell.innerHTML=`<div class="dot"></div><div class="ping-num">NODE ${num}</div><div class="ping-label" id="lbl-${num}">...</div><div class="ping-lat" id="lat-${num}"></div>`;
      grid.appendChild(cell);
    }
  });
}
function updateCell(num,status){const cell=document.getElementById(`cell-${num}`),lbl=document.getElementById(`lbl-${num}`),lat=document.getElementById(`lat-${num}`);if(!cell)return;if(!status){cell.className='ping-cell pending';lbl.textContent='...';lat.textContent='';return;}cell.className=`ping-cell ${status.alive?'alive':'dead'}`;lbl.textContent=status.alive?'ONLINE':'OFFLINE';lat.textContent=status.alive?status.latency:'';}
function updateStats(){let ok=0,ng=0,pend=0;for(let n=1;n<=100;n++){const s=pingData[`10.0.0.${n}`];if(!s)pend++;else if(s.alive)ok++;else ng++;}document.getElementById('cntOk').textContent=ok;document.getElementById('cntNg').textContent=ng;document.getElementById('cntPend').textContent=pend;CLUSTERS.forEach((cl,ci)=>{let clOk=0;for(let i=0;i<10;i++){if(pingData[`10.0.0.${cl.start+i}`]?.alive)clOk++;}const el=document.getElementById(`cl-stat-${ci}`);if(el){el.textContent=`${clOk} / 10`;el.style.color=clOk===10?'var(--ok)':clOk===0?'var(--ng)':'var(--accent)';}});}
async function loadStatus(){const r=await fetch('/api/ping_status');pingData=await r.json();for(let n=1;n<=100;n++)updateCell(n,pingData[`10.0.0.${n}`]);updateStats();document.getElementById('lastUpdate').textContent=`LAST UPDATE: ${new Date().toLocaleTimeString()}`;}
async function pingOne(ip,num){document.getElementById(`cell-${num}`).className='ping-cell pending';const r=await fetch('/api/ping_now',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip})});const data=await r.json();pingData[ip]=data;updateCell(num,data);updateStats();}
let refreshing=false;
async function refreshAll(){if(refreshing)return;refreshing=true;const btn=document.getElementById('refreshBtn');btn.innerHTML='<span class="spin">&#8635;</span> SCANNING...';btn.disabled=true;await loadStatus();btn.innerHTML='&#8635; REFRESH ALL';btn.disabled=false;refreshing=false;}
buildGrid();loadStatus();setInterval(loadStatus,15000);
</script>
</body>
</html>"""

with hosts_lock:
    hosts.update(load_hosts())

if __name__ == "__main__":
    print("BI Monitor:  http://localhost:5050")
    print("Ping Status: http://localhost:5050/ping")
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
