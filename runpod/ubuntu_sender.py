#!/usr/bin/env python3
"""Ubuntu → RunPod テキスト送信 (バッファリング付き)

Ubuntu PC (10.0.0.200) 上で動作。
各 M5Stack デバイスから OSC /mixer で受け取った生成文章を
バッファに溜め、一定文字数以上になったらまとめて
JSON ファイルとして RunPod へ SCP 転送する。

使い方:
    python ubuntu_sender.py
    python ubuntu_sender.py --config runpod_config.json
    python ubuntu_sender.py --dry-run   # SCP せずにローカル保存のみ
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

# ============================================================
# バッファリング設定 (後で config に移す候補)
# ============================================================
MIN_CHARS_TO_SEND = 50      # この文字数以上でバッファをフラッシュ
MAX_WAIT_SEC = 30.0          # 文字数未達でもこの秒数経過したらフラッシュ
MAX_BUFFER_ITEMS = 20        # バッファ内メッセージ数の上限 (溢れ防止)
# ============================================================

# ── グローバル ──
_cfg: dict = {}
_dry_run: bool = False
_send_lock = threading.Lock()
_stats = {"sent": 0, "failed": 0, "buffered": 0, "last_sent": None}

# バッファ
_buffer: list[dict] = []
_buffer_lock = threading.Lock()
_buffer_chars = 0
_buffer_first_time: float = 0.0


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


def flush_buffer(reason: str = ""):
    """バッファ内のテキストをまとめて1つのJSONとしてRunPodへ送信"""
    global _buffer, _buffer_chars, _buffer_first_time

    with _buffer_lock:
        if not _buffer:
            return
        items = _buffer[:]
        total_chars = _buffer_chars
        _buffer = []
        _buffer_chars = 0
        _buffer_first_time = 0.0

    merged_text = "\n".join(item["text"] for item in items)

    now = datetime.now().astimezone()
    ts = now.strftime("%Y%m%d_%H%M%S_%f")[:-3]
    filename = f"mixer_{ts}.json"

    payload = {
        "received_at": now.isoformat(),
        "address": "/mixer",
        "text": merged_text,
        "item_count": len(items),
        "total_chars": total_chars,
        "items": items,
    }

    reason_str = f" ({reason})" if reason else ""
    print(f"[sender] 📦 フラッシュ: {len(items)}件, {total_chars}文字{reason_str}")
    print(f"[sender]    テキスト: 「{merged_text[:80]}{'...' if len(merged_text) > 80 else ''}」")

    if _dry_run:
        dry_dir = Path("./dry_run_json")
        dry_dir.mkdir(exist_ok=True)
        (dry_dir / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[sender] (dry-run) 保存: {dry_dir / filename}")
        return

    with _send_lock:
        ok = upload_json(_cfg, payload, filename)
        if ok:
            _stats["sent"] += 1
            _stats["last_sent"] = now.isoformat()
            print(f"[sender] ✅ 送信完了: {filename} (通算: {_stats['sent']})")
        else:
            _stats["failed"] += 1
            print(f"[sender] ❌ 送信失敗 (通算失敗: {_stats['failed']})")


def on_mixer(address: str, *args):
    """OSC /mixer ハンドラ — バッファに追加"""
    global _buffer_chars, _buffer_first_time

    text = " ".join(str(a) for a in args).strip()
    if not text:
        print(f"[sender] ⚠️  空テキスト受信、スキップ")
        return

    now = datetime.now().astimezone()
    item = {
        "text": text,
        "received_at": now.isoformat(),
        "address": address,
    }

    with _buffer_lock:
        _buffer.append(item)
        _buffer_chars += len(text)
        if _buffer_first_time == 0.0:
            _buffer_first_time = time.time()

        current_chars = _buffer_chars
        current_count = len(_buffer)

    _stats["buffered"] = current_count
    print(f"[sender] 受信: 「{text[:50]}{'...' if len(text) > 50 else ''}」"
          f" (バッファ: {current_count}件/{current_chars}文字)")

    # 文字数閾値チェック
    if current_chars >= MIN_CHARS_TO_SEND:
        flush_buffer(reason=f"{current_chars}文字 >= {MIN_CHARS_TO_SEND}")

    # メッセージ数上限チェック
    elif current_count >= MAX_BUFFER_ITEMS:
        flush_buffer(reason=f"{current_count}件 >= {MAX_BUFFER_ITEMS}")


def buffer_timeout_watcher():
    """バッファのタイムアウト監視スレッド"""
    while True:
        time.sleep(1.0)

        with _buffer_lock:
            if not _buffer or _buffer_first_time == 0.0:
                continue
            elapsed = time.time() - _buffer_first_time
            count = len(_buffer)
            chars = _buffer_chars

        if elapsed >= MAX_WAIT_SEC:
            flush_buffer(reason=f"タイムアウト {elapsed:.0f}s >= {MAX_WAIT_SEC}s, {count}件/{chars}文字")


def on_status(address: str, *args):
    """OSC /runpod/status で統計表示"""
    with _buffer_lock:
        buf_count = len(_buffer)
        buf_chars = _buffer_chars
    print(f"[sender] 統計: sent={_stats['sent']} failed={_stats['failed']} "
          f"buffer={buf_count}件/{buf_chars}文字 last={_stats['last_sent']}")


def on_flush(address: str, *args):
    """OSC /runpod/flush でバッファ強制フラッシュ"""
    flush_buffer(reason="手動フラッシュ (/runpod/flush)")


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

    # タイムアウト監視スレッド起動
    watcher = threading.Thread(target=buffer_timeout_watcher, daemon=True)
    watcher.start()

    # OSCサーバー設定
    disp = Dispatcher()
    disp.map(osc_address, on_mixer)
    disp.map("/runpod/status", on_status)
    disp.map("/runpod/flush", on_flush)

    server = BlockingOSCUDPServer((osc_ip, osc_port), disp)

    print(f"[sender] ============================")
    print(f"[sender] Ubuntu → RunPod テキスト送信")
    print(f"[sender] OSC受信: udp://{osc_ip}:{osc_port}  {osc_address}")
    print(f"[sender] バッファ: {MIN_CHARS_TO_SEND}文字以上 or {MAX_WAIT_SEC}s経過 or {MAX_BUFFER_ITEMS}件 でフラッシュ")
    if _dry_run:
        print(f"[sender] モード: dry-run (ローカル保存のみ)")
    else:
        print(f"[sender] RunPod先: {_cfg['ssh']['user']}@{_cfg['ssh']['host']}")
        print(f"[sender] リモート: {_cfg['runpod']['osc_json_dir']}")
    print(f"[sender] ============================")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        flush_buffer(reason="終了時フラッシュ")
        print(f"\n[sender] 終了。sent={_stats['sent']} failed={_stats['failed']}")


if __name__ == "__main__":
    main()
