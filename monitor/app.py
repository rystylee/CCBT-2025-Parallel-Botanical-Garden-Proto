"""
Monitor Web Application for Parallel Botanical Garden.

Provides:
  - Device overview (cluster / node topology)
  - Interactive SSH terminal to individual devices (via xterm.js + WebSocket)
  - Command broadcast to selected nodes, clusters, or all devices
"""

import argparse
import csv
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from loguru import logger

from monitor.ssh_manager import SSHManager

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

CLUSTER_SIZE = 10  # devices per cluster


@dataclass
class Device:
    device_id: int
    ip_address: str
    target_ids: List[int]
    cluster_id: int  # 1-based

    @property
    def is_gateway(self) -> bool:
        """Gateway nodes connect clusters (IDs 6,16,26,...,96)."""
        return self.device_id % CLUSTER_SIZE == 6 or (
            self.device_id % CLUSTER_SIZE == 0 and self.device_id > 0
        )


def load_devices(csv_path: str) -> Dict[int, Device]:
    """Load device list from networks.csv."""
    devices: Dict[int, Device] = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            did = int(row["ID"])
            ip = row["IP"].strip()
            targets = [int(t.strip()) for t in row["To"].strip().split(",") if t.strip()]
            cluster_id = ((did - 1) // CLUSTER_SIZE) + 1
            devices[did] = Device(
                device_id=did, ip_address=ip, target_ids=targets, cluster_id=cluster_id
            )
    return devices


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    csv_path: str = "config/networks.csv",
    ssh_username: str = "m5stack",
    ssh_password: Optional[str] = None,
    ssh_key_path: Optional[str] = None,
) -> tuple:
    """Create and configure the Flask app + SocketIO."""

    base_dir = Path(__file__).resolve().parent
    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    app.config["SECRET_KEY"] = os.urandom(24).hex()

    socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

    # -- Load topology --
    devices = load_devices(csv_path)
    num_clusters = max(d.cluster_id for d in devices.values())
    logger.info(f"Loaded {len(devices)} devices in {num_clusters} clusters")

    # -- SSH manager --
    ssh_mgr = SSHManager(
        username=ssh_username,
        password=ssh_password,
        key_path=ssh_key_path,
    )

    # -- Helper to build target list --
    def resolve_targets(scope: str, scope_value: Optional[str] = None) -> List[Dict]:
        """
        Resolve scope to a list of {device_id, host}.

        scope: "all" | "cluster" | "node"
        scope_value: cluster id or comma-separated node ids
        """
        targets = []
        if scope == "all":
            for d in devices.values():
                targets.append({"device_id": d.device_id, "host": d.ip_address})
        elif scope == "cluster" and scope_value:
            cid = int(scope_value)
            for d in devices.values():
                if d.cluster_id == cid:
                    targets.append({"device_id": d.device_id, "host": d.ip_address})
        elif scope == "node" and scope_value:
            for nid_str in scope_value.split(","):
                nid = int(nid_str.strip())
                if nid in devices:
                    d = devices[nid]
                    targets.append({"device_id": d.device_id, "host": d.ip_address})
        return targets

    # -----------------------------------------------------------------------
    # HTTP routes
    # -----------------------------------------------------------------------

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/devices")
    def api_devices():
        """Return device topology as JSON."""
        clusters: Dict[int, list] = {}
        for d in sorted(devices.values(), key=lambda x: x.device_id):
            clusters.setdefault(d.cluster_id, []).append(
                {
                    "device_id": d.device_id,
                    "ip": d.ip_address,
                    "targets": d.target_ids,
                    "is_gateway": d.is_gateway,
                }
            )
        return jsonify({"clusters": clusters, "total": len(devices)})

    # -----------------------------------------------------------------------
    # WebSocket: Interactive SSH terminal
    # -----------------------------------------------------------------------

    @socketio.on("ssh_connect")
    def handle_ssh_connect(data):
        """Open an interactive SSH session to a device."""
        device_id = int(data.get("device_id", 0))
        sid = request.sid

        if device_id not in devices:
            emit("ssh_error", {"message": f"Unknown device ID: {device_id}"})
            return

        dev = devices[device_id]
        emit("ssh_status", {"message": f"Connecting to device {device_id} ({dev.ip_address})..."})

        session = ssh_mgr.open_interactive(sid, device_id, dev.ip_address)
        if session is None:
            emit("ssh_error", {"message": f"SSH connection failed to {dev.ip_address}"})
            return

        emit("ssh_connected", {"device_id": device_id, "host": dev.ip_address})

        # Start reader thread for this session
        def _reader():
            while True:
                s = ssh_mgr.get_session(sid)
                if s is None or not s.active:
                    break
                output = ssh_mgr.read_from_session(sid)
                if output:
                    socketio.emit("ssh_output", {"data": output}, to=sid)
                else:
                    time.sleep(0.05)
            socketio.emit("ssh_disconnected", {}, to=sid)

        threading.Thread(target=_reader, daemon=True).start()

    @socketio.on("ssh_input")
    def handle_ssh_input(data):
        """Forward keystrokes to the SSH channel."""
        ssh_mgr.write_to_session(request.sid, data.get("data", ""))

    @socketio.on("ssh_resize")
    def handle_ssh_resize(data):
        """Handle terminal resize."""
        ssh_mgr.resize_session(
            request.sid,
            int(data.get("cols", 120)),
            int(data.get("rows", 40)),
        )

    @socketio.on("ssh_disconnect")
    def handle_ssh_disconnect():
        """Cleanly close the SSH session."""
        ssh_mgr.close_interactive(request.sid)
        emit("ssh_disconnected", {})

    @socketio.on("disconnect")
    def handle_ws_disconnect():
        """Cleanup on WebSocket disconnect."""
        ssh_mgr.close_interactive(request.sid)

    # -----------------------------------------------------------------------
    # WebSocket: Command broadcast
    # -----------------------------------------------------------------------

    @socketio.on("broadcast_command")
    def handle_broadcast(data):
        """
        Execute a command on multiple devices and stream results back.

        data: {
            command: str,
            scope: "all" | "cluster" | "node",
            scope_value: str (cluster id or node ids),
        }
        """
        command = data.get("command", "").strip()
        scope = data.get("scope", "node")
        scope_value = data.get("scope_value", "")
        sid = request.sid

        if not command:
            emit("broadcast_error", {"message": "Empty command"})
            return

        targets = resolve_targets(scope, scope_value)
        if not targets:
            emit("broadcast_error", {"message": "No targets resolved"})
            return

        emit(
            "broadcast_start",
            {"total": len(targets), "command": command, "scope": scope},
        )

        def on_result(result):
            socketio.emit(
                "broadcast_result",
                {
                    "device_id": result.device_id,
                    "host": result.host,
                    "exit_code": result.exit_code,
                    "stdout": result.stdout[-4096:],  # cap output size
                    "stderr": result.stderr[-2048:],
                    "success": result.success,
                    "elapsed": round(result.elapsed, 2),
                },
                to=sid,
            )

        def _run():
            results = ssh_mgr.broadcast_command(targets, command, on_result=on_result)
            ok = sum(1 for r in results if r.success)
            socketio.emit(
                "broadcast_done",
                {"total": len(results), "success": ok, "failed": len(results) - ok},
                to=sid,
            )

        threading.Thread(target=_run, daemon=True).start()

    @socketio.on("save_snippet")
    def handle_save_snippet(data):
        """Save a command snippet for reuse."""
        # For now, just acknowledge — a real implementation could persist to disk/DB
        emit("snippet_saved", {"name": data.get("name"), "command": data.get("command")})

    return app, socketio


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def parse_args():
    p = argparse.ArgumentParser(description="Parallel Botanical Garden — Monitor")
    p.add_argument("--csv", default="config/networks.csv", help="Path to networks.csv")
    p.add_argument("--host", default="0.0.0.0", help="Bind address")
    p.add_argument("--port", type=int, default=5000, help="HTTP port")
    p.add_argument("--ssh-user", default="m5stack", help="SSH username for devices")
    p.add_argument("--ssh-password", default=None, help="SSH password")
    p.add_argument("--ssh-key", default=None, help="SSH private key path")
    p.add_argument("--debug", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    app, socketio = create_app(
        csv_path=args.csv,
        ssh_username=args.ssh_user,
        ssh_password=args.ssh_password,
        ssh_key_path=args.ssh_key,
    )
    logger.info(f"Monitor starting on http://{args.host}:{args.port}")
    socketio.run(app, host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
