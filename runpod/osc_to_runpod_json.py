#!/usr/bin/env python3
import json
import os
import tempfile
import subprocess
from datetime import datetime

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

# ===== OSC受信設定 =====
OSC_IP = os.getenv("OSC_LISTEN_IP", "0.0.0.0")
OSC_PORT = int(os.getenv("OSC_LISTEN_PORT", "8000"))

# ===== Runpod (SSH over exposed TCP) 設定 =====
RUNPOD_USER = os.getenv("RUNPOD_USER", "root")
RUNPOD_HOST = os.getenv("RUNPOD_HOST", "194.68.245.46")
RUNPOD_PORT = int(os.getenv("RUNPOD_PORT", "22004"))
SSH_KEY = os.path.expanduser(os.getenv("SSH_KEY", "~/.ssh/id_ed25519"))

# Runpod側の保存先（~ ではなく絶対パスにして確実に）
REMOTE_DIR = os.getenv("REMOTE_DIR", "/workspace/seed-vc/osc")

SSH = [
    "ssh", "-i", SSH_KEY, "-p", str(RUNPOD_PORT),
    "-o", "StrictHostKeyChecking=accept-new",
    f"{RUNPOD_USER}@{RUNPOD_HOST}",
]
SCP = [
    "scp", "-i", SSH_KEY, "-P", str(RUNPOD_PORT),
    "-o", "StrictHostKeyChecking=accept-new",
]
# もし scp が SFTPモードでコケる特殊ケースがあれば、次の1行を有効化（旧scpプロトコル強制）
# SCP.insert(1, "-O")


def ensure_remote_dir():
    subprocess.run(SSH + [f"mkdir -p {REMOTE_DIR}"], check=True)


def upload_json(payload: dict, remote_filename: str):
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
        f.write("\n")
        local_path = f.name

    try:
        remote = f"{RUNPOD_USER}@{RUNPOD_HOST}:{REMOTE_DIR}/{remote_filename}"
        subprocess.run(SCP + [local_path, remote], check=True)
        print(f"[SAVED] {REMOTE_DIR}/{remote_filename}")
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass


def on_mixer(address, *args):
    now = datetime.now().astimezone()
    ts = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]  # ミリ秒
    filename = f"mixer_{ts}.json"

    text = " ".join(str(a) for a in args).strip()

    payload = {
        "received_at": now.isoformat(),
        "address": address,
        "args": list(args),
        "text": text,
    }

    try:
        upload_json(payload, filename)
        print(f"[OSC] {address} {text}")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] ssh/scp failed: {e}")


def main():
    ensure_remote_dir()

    disp = Dispatcher()
    disp.map("/mixer", on_mixer)

    server = BlockingOSCUDPServer((OSC_IP, OSC_PORT), disp)
    print(f"[LISTEN] udp://{OSC_IP}:{OSC_PORT}  /mixer")
    server.serve_forever()


if __name__ == "__main__":
    main()
