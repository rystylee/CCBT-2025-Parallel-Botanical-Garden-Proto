from flask import Flask, render_template_string, request, jsonify
from pythonosc import udp_client
import threading, time, json, os

app = Flask(__name__)

# ホスト管理
hosts = {}
hosts_lock = threading.Lock()
fade_threads = {}

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
            return  # キャンセル
        v = start_val + (end_val - start_val) * (i / steps)
        with hosts_lock:
            h = hosts.get(host_id)
            if not h:
                return
            h["value"] = round(v, 4)
        send_osc(h["ip"], h["port"], v)
        time.sleep(dt)

@app.route("/")
def index():
    return render_template_string(HTML)

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
            "id": host_id,
            "name": data.get("name", f"Light {host_id}"),
            "ip": data["ip"],
            "port": int(data.get("port", 9000)),
            "value": 0.0,
            "fade_up": float(data.get("fade_up", 2.0)),
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
    action = data.get("action")  # "on", "off", "fade_up", "fade_down"
    with hosts_lock:
        ids = list(hosts.keys())
    for host_id in ids:
        if action in ("on", "off"):
            val = 1.0 if action == "on" else 0.0
            with hosts_lock:
                h = hosts.get(host_id)
                if h:
                    h["value"] = val
            send_osc(h["ip"], h["port"], val)
        elif action in ("fade_up", "fade_down"):
            direction = "up" if action == "fade_up" else "down"
            with hosts_lock:
                h = hosts.get(host_id)
                if not h:
                    continue
                start = h["value"]
                end = 1.0 if direction == "up" else 0.0
                duration = h["fade_up"] if direction == "up" else h["fade_down"]
            t = threading.Thread(target=fade_worker, args=(host_id, start, end, duration), daemon=True)
            fade_threads[host_id] = t
            t.start()
    return jsonify({"ok": True})

HTML = r"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LED CONTROLLER</title>
<link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Barlow:wght@300;500;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0a0a0f;
    --panel: #111118;
    --border: #1e1e2e;
    --accent: #f0c040;
    --accent2: #40c0f0;
    --dim: #444460;
    --text: #cccce0;
    --on: #f0c040;
    --off: #222230;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: 'Barlow', sans-serif; min-height: 100vh; }

  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 16px 24px;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
  }
  header h1 { font-family: 'Share Tech Mono', monospace; font-size: 1.1rem; color: var(--accent); letter-spacing: 4px; }
  .status-bar { font-family: 'Share Tech Mono', monospace; font-size: 0.72rem; color: var(--dim); }

  .global-bar {
    display: flex; gap: 10px; padding: 14px 24px;
    background: #0d0d14; border-bottom: 1px solid var(--border);
    flex-wrap: wrap; align-items: center;
  }
  .global-bar label { font-size: 0.75rem; color: var(--dim); letter-spacing: 2px; margin-right: 4px; }
  .btn {
    font-family: 'Share Tech Mono', monospace; font-size: 0.75rem;
    padding: 7px 16px; border: 1px solid var(--dim); background: transparent;
    color: var(--text); cursor: pointer; letter-spacing: 1px; transition: all 0.15s;
  }
  .btn:hover { border-color: var(--accent); color: var(--accent); }
  .btn.danger:hover { border-color: #f04040; color: #f04040; }
  .btn.primary { border-color: var(--accent); color: var(--accent); }
  .btn.accent2 { border-color: var(--accent2); color: var(--accent2); }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px; padding: 16px 24px;
  }

  .card {
    background: var(--panel); border: 1px solid var(--border);
    padding: 14px; position: relative; transition: border-color 0.2s;
  }
  .card:hover { border-color: #333344; }
  .card.active { border-color: var(--accent); box-shadow: 0 0 12px rgba(240,192,64,0.08); }

  .card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
  .card-name {
    font-size: 0.8rem; font-weight: 700; color: var(--text); letter-spacing: 1px;
    cursor: pointer; max-width: 130px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .card-ip { font-family: 'Share Tech Mono', monospace; font-size: 0.65rem; color: var(--dim); margin-top: 2px; }
  .del-btn { background: none; border: none; color: var(--dim); cursor: pointer; font-size: 0.9rem; padding: 0 2px; }
  .del-btn:hover { color: #f04040; }

  .value-display {
    font-family: 'Share Tech Mono', monospace; font-size: 1.6rem;
    color: var(--accent); text-align: center; margin: 8px 0 6px;
    transition: color 0.2s;
  }
  .value-display.dim { color: var(--dim); }

  input[type=range] {
    width: 100%; height: 4px; appearance: none;
    background: linear-gradient(to right, var(--accent) var(--pct, 0%), var(--off) var(--pct, 0%));
    border-radius: 2px; outline: none; cursor: pointer; margin-bottom: 10px;
  }
  input[type=range]::-webkit-slider-thumb {
    appearance: none; width: 14px; height: 14px; background: var(--accent);
    border-radius: 50%; border: 2px solid var(--bg);
  }

  .card-actions { display: flex; gap: 6px; }
  .fade-btn {
    flex: 1; font-family: 'Share Tech Mono', monospace; font-size: 0.65rem;
    padding: 5px 0; border: 1px solid var(--border); background: transparent;
    color: var(--dim); cursor: pointer; transition: all 0.15s; letter-spacing: 1px;
  }
  .fade-btn:hover { border-color: var(--accent2); color: var(--accent2); }

  /* Add host modal */
  .modal-bg {
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,0.8); z-index: 100; align-items: center; justify-content: center;
  }
  .modal-bg.show { display: flex; }
  .modal {
    background: var(--panel); border: 1px solid var(--accent);
    padding: 28px; width: 360px; max-width: 95vw;
  }
  .modal h2 { font-family: 'Share Tech Mono', monospace; font-size: 0.9rem; color: var(--accent); margin-bottom: 20px; letter-spacing: 3px; }
  .field { margin-bottom: 14px; }
  .field label { display: block; font-size: 0.7rem; color: var(--dim); letter-spacing: 2px; margin-bottom: 5px; }
  .field input {
    width: 100%; background: var(--bg); border: 1px solid var(--border);
    color: var(--text); padding: 8px 10px; font-family: 'Share Tech Mono', monospace; font-size: 0.85rem;
    outline: none; transition: border-color 0.15s;
  }
  .field input:focus { border-color: var(--accent); }
  .modal-actions { display: flex; gap: 10px; margin-top: 20px; }

  .bulk-input {
    width: 100%; min-height: 80px; background: var(--bg); border: 1px solid var(--border);
    color: var(--text); padding: 8px 10px; font-family: 'Share Tech Mono', monospace;
    font-size: 0.78rem; outline: none; resize: vertical;
  }
  .bulk-input:focus { border-color: var(--accent); }

  .tab-bar { display: flex; gap: 0; margin-bottom: 16px; }
  .tab { padding: 7px 18px; font-size: 0.72rem; letter-spacing: 2px; cursor: pointer; border: 1px solid var(--border); color: var(--dim); background: transparent; font-family: 'Share Tech Mono', monospace; }
  .tab.active { border-color: var(--accent); color: var(--accent); background: rgba(240,192,64,0.05); }
  .tab-content { display: none; }
  .tab-content.active { display: block; }
</style>
</head>
<body>
<header>
  <div>
    <h1>◈ LED CONTROLLER</h1>
    <div class="status-bar" id="statusBar">HOSTS: 0 / ACTIVE: 0</div>
  </div>
  <div style="display:flex;gap:8px;flex-wrap:wrap">
    <button class="btn primary" onclick="openModal()">+ ADD HOST</button>
    <button class="btn accent2" onclick="openBulkModal()">+ BULK ADD</button>
  </div>
</header>

<div class="global-bar">
  <label>ALL:</label>
  <button class="btn primary" onclick="allAction('on')">ALL ON</button>
  <button class="btn" onclick="allAction('off')">ALL OFF</button>
  <button class="btn accent2" onclick="allAction('fade_up')">FADE UP ALL</button>
  <button class="btn" onclick="allAction('fade_down')">FADE DOWN ALL</button>
  <div style="flex:1"></div>
  <label>GLOBAL FADE:</label>
  <label style="font-size:0.72rem">UP</label>
  <input type="number" id="gFadeUp" value="2" step="0.1" min="0.1" style="width:60px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px;font-family:'Share Tech Mono',monospace;font-size:0.8rem">
  <label style="font-size:0.72rem">DOWN</label>
  <input type="number" id="gFadeDown" value="2" step="0.1" min="0.1" style="width:60px;background:var(--bg);border:1px solid var(--border);color:var(--text);padding:5px;font-family:'Share Tech Mono',monospace;font-size:0.8rem">
  <button class="btn" onclick="applyGlobalFade()">APPLY</button>
</div>

<div class="grid" id="grid"></div>

<!-- Add modal -->
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

<!-- Bulk modal -->
<div class="modal-bg" id="bulkModal">
  <div class="modal" style="width:480px">
    <h2>BULK ADD HOSTS</h2>
    <div class="tab-bar">
      <div class="tab active" onclick="switchTab('range')">IP RANGE</div>
      <div class="tab" onclick="switchTab('list')">LIST</div>
    </div>
    <div class="tab-content active" id="tab-range">
      <div class="field"><label>IP PREFIX (e.g. 10.0.0)</label><input id="b_prefix" placeholder="10.0.0"></div>
      <div class="field"><label>START - END</label>
        <div style="display:flex;gap:8px">
          <input id="b_start" placeholder="1" type="number" min="1" max="254">
          <input id="b_end" placeholder="100" type="number" min="1" max="254">
        </div>
      </div>
      <div class="field"><label>PORT</label><input id="b_port" value="9000"></div>
    </div>
    <div class="tab-content" id="tab-list">
      <div class="field">
        <label>ONE PER LINE: name,ip,port (port optional)</label>
        <textarea class="bulk-input" id="b_list" placeholder="Light A,10.0.1.1,9000&#10;Light B,10.0.1.2&#10;Light C,10.0.1.3"></textarea>
      </div>
    </div>
    <div class="modal-actions">
      <button class="btn primary" onclick="bulkAdd()">ADD ALL</button>
      <button class="btn" onclick="closeBulkModal()">CANCEL</button>
    </div>
  </div>
</div>

<script>
let hosts = {};
let bulkTab = 'range';

async function loadHosts() {
  const r = await fetch('/api/hosts');
  hosts = await r.json();
  renderGrid();
}

function renderGrid() {
  const grid = document.getElementById('grid');
  const ids = Object.keys(hosts);
  grid.innerHTML = '';
  ids.forEach(id => {
    const h = hosts[id];
    const pct = (h.value * 100).toFixed(0);
    const isOn = h.value > 0.01;
    const card = document.createElement('div');
    card.className = `card${isOn ? ' active' : ''}`;
    card.id = `card-${id}`;
    card.innerHTML = `
      <div class="card-header">
        <div>
          <div class="card-name" title="${h.name}">${h.name}</div>
          <div class="card-ip">${h.ip}:${h.port}</div>
        </div>
        <button class="del-btn" onclick="deleteHost('${id}')">✕</button>
      </div>
      <div class="value-display ${isOn ? '' : 'dim'}" id="val-${id}">${h.value.toFixed(2)}</div>
      <input type="range" min="0" max="1" step="0.01" value="${h.value}"
        style="--pct:${pct}%"
        oninput="onSlider('${id}', this)"
        onchange="sendValue('${id}', parseFloat(this.value))">
      <div class="card-actions">
        <button class="fade-btn" onclick="fade('${id}','up')">▲ FADE UP</button>
        <button class="fade-btn" onclick="fade('${id}','down')">▼ FADE DOWN</button>
      </div>
    `;
    grid.appendChild(card);
  });
  updateStatus();
}

function onSlider(id, el) {
  const v = parseFloat(el.value);
  const pct = (v * 100).toFixed(0) + '%';
  el.style.setProperty('--pct', pct);
  const vEl = document.getElementById(`val-${id}`);
  if (vEl) { vEl.textContent = v.toFixed(2); vEl.className = `value-display ${v > 0.01 ? '' : 'dim'}`; }
  const card = document.getElementById(`card-${id}`);
  if (card) card.className = `card${v > 0.01 ? ' active' : ''}`;
  if (hosts[id]) hosts[id].value = v;
}

async function sendValue(id, value) {
  await fetch(`/api/send/${id}`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({value}) });
  updateStatus();
}

async function fade(id, direction) {
  await fetch(`/api/fade/${id}`, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({direction}) });
  pollFade(id);
}

function pollFade(id) {
  let count = 0;
  const iv = setInterval(async () => {
    const r = await fetch('/api/hosts');
    const h = await r.json();
    if (h[id]) {
      hosts[id] = h[id];
      const v = h[id].value;
      const pct = (v * 100).toFixed(0) + '%';
      const slider = document.querySelector(`#card-${id} input[type=range]`);
      if (slider) { slider.value = v; slider.style.setProperty('--pct', pct); }
      const vEl = document.getElementById(`val-${id}`);
      if (vEl) { vEl.textContent = v.toFixed(2); vEl.className = `value-display ${v > 0.01 ? '' : 'dim'}`; }
      const card = document.getElementById(`card-${id}`);
      if (card) card.className = `card${v > 0.01 ? ' active' : ''}`;
    }
    count++;
    if (count > 100) clearInterval(iv);
    updateStatus();
  }, 200);
}

async function allAction(action) {
  await fetch('/api/all', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action}) });
  if (action === 'fade_up' || action === 'fade_down') {
    Object.keys(hosts).forEach(id => pollFade(id));
  } else {
    await loadHosts();
  }
}

async function applyGlobalFade() {
  const up = parseFloat(document.getElementById('gFadeUp').value);
  const dn = parseFloat(document.getElementById('gFadeDown').value);
  for (const id of Object.keys(hosts)) {
    await fetch(`/api/hosts/${id}`, { method:'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify({fade_up: up, fade_down: dn}) });
  }
  await loadHosts();
}

async function deleteHost(id) {
  if (!confirm('このホストを削除しますか？')) return;
  await fetch(`/api/hosts/${id}`, { method:'DELETE' });
  delete hosts[id];
  renderGrid();
}

function updateStatus() {
  const total = Object.keys(hosts).length;
  const active = Object.values(hosts).filter(h => h.value > 0.01).length;
  document.getElementById('statusBar').textContent = `HOSTS: ${total} / ACTIVE: ${active}`;
}

function openModal() { document.getElementById('addModal').classList.add('show'); document.getElementById('f_name').focus(); }
function closeModal() { document.getElementById('addModal').classList.remove('show'); }
function openBulkModal() { document.getElementById('bulkModal').classList.add('show'); }
function closeBulkModal() { document.getElementById('bulkModal').classList.remove('show'); }

function switchTab(tab) {
  bulkTab = tab;
  document.querySelectorAll('.tab').forEach((t,i) => t.classList.toggle('active', (i===0&&tab==='range')||(i===1&&tab==='list')));
  document.querySelectorAll('.tab-content').forEach((c,i) => c.classList.toggle('active', (i===0&&tab==='range')||(i===1&&tab==='list')));
}

async function addHost() {
  const data = {
    name: document.getElementById('f_name').value || 'Light',
    ip: document.getElementById('f_ip').value,
    port: parseInt(document.getElementById('f_port').value) || 9000,
    fade_up: parseFloat(document.getElementById('f_fup').value) || 2,
    fade_down: parseFloat(document.getElementById('f_fdn').value) || 2,
  };
  if (!data.ip) return;
  await fetch('/api/hosts', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(data) });
  closeModal();
  await loadHosts();
}

async function bulkAdd() {
  const jobs = [];
  if (bulkTab === 'range') {
    const prefix = document.getElementById('b_prefix').value.trim();
    const start = parseInt(document.getElementById('b_start').value);
    const end = parseInt(document.getElementById('b_end').value);
    const port = parseInt(document.getElementById('b_port').value) || 9000;
    if (!prefix || isNaN(start) || isNaN(end)) return alert('入力を確認してください');
    for (let i = start; i <= end; i++) {
      jobs.push({ name: `${prefix}.${i}`, ip: `${prefix}.${i}`, port });
    }
  } else {
    const lines = document.getElementById('b_list').value.trim().split('\n');
    for (const line of lines) {
      if (!line.trim()) continue;
      const parts = line.split(',').map(s => s.trim());
      if (parts.length < 2) continue;
      jobs.push({ name: parts[0], ip: parts[1], port: parseInt(parts[2]) || 9000 });
    }
  }
  for (const job of jobs) {
    await fetch('/api/hosts', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(job) });
  }
  closeBulkModal();
  await loadHosts();
}

// キーボードショートカット
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeModal(); closeBulkModal(); }
});

loadHosts();
</script>
</body>
</html>"""

with hosts_lock:
    hosts.update(load_hosts())

if __name__ == "__main__":
    print("LED Dashboard: http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False, threaded=True)
