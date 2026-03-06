#!/usr/bin/env python3
"""Ubuntu → RunPod テキスト送信

Ubuntu PC (10.0.0.200) 上で動作。
各 M5Stack デバイスから OSC /mixer で受け取った生成文章を
JSON ファイルとして RunPod へ SCP 転送する。

使い方:
    python ubuntu_sender.py
    python ubuntu_sender.py --config runpod_config.json
    python ubuntu_sender.py --dry-run   # SCP せずにローカル保存のみ

環境変数でも上書き可能:
    OSC_LISTEN_IP=0.0.0.0  OSC_LISTEN_PORT=8000  python ubuntu_sender.py
"""

import argparse
import json
import os
import sys
import tempfile
import time
import threading
from datetime import datetime
from pathlib import Path

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from ssh_helper import load_config, ssh_run, scp_upload

# ── グローバル ──
_cfg: dict = {}
_dry_run: bool = False
_send_lock = threading.Lock()
_stats = {"sent": 0, "failed": 0, "last_sent": None}


def ensure_remote_dir(cfg: dict):
    """RunPod側のOSC JSONディレクトリを作成"""
    remote_dir = cfg["runpod"]["osc_json_dir"]
    try:
        ssh_run(cfg, f"mkdir -p {remote_dir}", timeout=15)
        print(f"[sender] リモートディレクトリ確認: {remote_dir}")
    except Exception as e:
        print(f"[sender] ⚠️  リモートディレクトリ作成失敗: {e}", file=sys.stderr)


def upload_json(cfg: dict, payload: dict, filename: str):
    """JSONをRunPodへSCP転送"""
    remote_dir = cfg["runpod"]["osc_json_dir"]

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".json", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
        f.write("\n")
        local_path = f.name

    try:
        remote_path = f"{remote_dir}/{filename}"
        scp_upload(cfg, local_path, remote_path)
        return True
    except Exception as e:
        print(f"[sender] ❌ SCP失敗: {filename} → {e}", file=sys.stderr)
        return False
    finally:
        try:
            os.unlink(local_path)
        except OSError:
            pass


def on_mixer(address: str, *args):
    """OSC /mixer ハンドラ"""
    now = datetime.now().astimezone()
    ts = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
    filename = f"mixer_{ts}.json"

    text = " ".join(str(a) for a in args).strip()
    if not text:
        print(f"[sender] ⚠️  空テキスト受信、スキップ")
        return

    payload = {
        "received_at": now.isoformat(),
        "address": address,
        "args": list(args),
        "text": text,
    }

    print(f"[sender] 受信: {address} → 「{text[:60]}{'...' if len(text) > 60 else ''}」")

    if _dry_run:
        dry_dir = Path("./dry_run_json")
        dry_dir.mkdir(exist_ok=True)
        (dry_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[sender] (dry-run) 保存: {dry_dir / filename}")
        return

    # SCP送信 (スレッドセーフ)
    with _send_lock:
        ok = upload_json(_cfg, payload, filename)
        if ok:
            _stats["sent"] += 1
            _stats["last_sent"] = now.isoformat()
            print(f"[sender] ✅ 送信完了: {filename} (通算: {_stats['sent']})")
        else:
            _stats["failed"] += 1
            print(f"[sender] ❌ 送信失敗 (通算失敗: {_stats['failed']})")


def on_status(address: str, *args):
    """OSC /runpod/status で統計表示"""
    print(f"[sender] 統計: sent={_stats['sent']} failed={_stats['failed']} last={_stats['last_sent']}")


def main():
    global _cfg, _dry_run

    parser = argparse.ArgumentParser(description="Ubuntu → RunPod テキスト送信")
    parser.add_argument("--config", default=None, help="設定ファイルパス")
    parser.add_argument("--dry-run", action="store_true", help="SCP せずにローカル保存のみ")
    parser.add_argument("--osc-ip", default=None, help="OSC受信IP (デフォルト: config値)")
    parser.add_argument("--osc-port", type=int, default=None, help="OSC受信ポート (デフォルト: config値)")
    args = parser.parse_args()

    _cfg = load_config(args.config)
    _dry_run = args.dry_run

    sender_cfg = _cfg.get("ubuntu_sender", {})
    osc_ip = args.osc_ip or os.getenv("OSC_LISTEN_IP") or sender_cfg.get("osc_listen_ip", "0.0.0.0")
    osc_port = args.osc_port or int(os.getenv("OSC_LISTEN_PORT", "0")) or sender_cfg.get("osc_listen_port", 8000)
    osc_address = sender_cfg.get("osc_address", "/mixer")

    if not _dry_run:
        print("[sender] RunPod接続テスト...")
        ensure_remote_dir(_cfg)

    # OSCサーバー設定
    disp = Dispatcher()
    disp.map(osc_address, on_mixer)
    disp.map("/runpod/status", on_status)

    server = BlockingOSCUDPServer((osc_ip, osc_port), disp)

    print(f"[sender] ============================")
    print(f"[sender] Ubuntu → RunPod テキスト送信")
    print(f"[sender] OSC受信: udp://{osc_ip}:{osc_port}  {osc_address}")
    if _dry_run:
        print(f"[sender] モード: dry-run (ローカル保存のみ)")
    else:
        print(f"[sender] RunPod先: {_cfg['ssh']['user']}@{_cfg['ssh']['host']}")
        print(f"[sender] リモート: {_cfg['runpod']['osc_json_dir']}")
    print(f"[sender] ============================")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print(f"\n[sender] 終了。sent={_stats['sent']} failed={_stats['failed']}")


if __name__ == "__main__":
    main()
