"""RunPod SSH / SCP ヘルパー

runpod_config.json の "ssh" セクションを読んで
ssh / scp コマンドのベース引数を生成するユーティリティ。
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

_DEFAULT_CONFIG_PATH = Path(__file__).parent / "runpod_config.json"


def load_config(config_path: Optional[str] = None) -> dict:
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def ssh_base(cfg: dict) -> list[str]:
    """ssh コマンドのベース引数リストを返す"""
    s = cfg["ssh"]
    key = os.path.expanduser(s["key"])
    cmd = [
        "ssh",
        "-i", key,
        "-p", str(s["port"]),
    ]
    cmd += s.get("options", [])
    if s.get("connect_timeout"):
        cmd += ["-o", f"ConnectTimeout={s['connect_timeout']}"]
    cmd.append(f"{s['user']}@{s['host']}")
    return cmd


def scp_base(cfg: dict) -> list[str]:
    """scp コマンドのベース引数リストを返す"""
    s = cfg["ssh"]
    key = os.path.expanduser(s["key"])
    cmd = [
        "scp",
        "-i", key,
        "-P", str(s["port"]),
    ]
    # scp は -o オプションも受け付ける
    cmd += s.get("options", [])
    return cmd


def scp_target(cfg: dict) -> str:
    """scp の user@host プレフィクスを返す"""
    s = cfg["ssh"]
    return f"{s['user']}@{s['host']}"


def ssh_run(cfg: dict, remote_cmd: str, check: bool = True,
            capture: bool = True, timeout: int = 60) -> subprocess.CompletedProcess:
    """リモートでコマンドを実行"""
    cmd = ssh_base(cfg) + [remote_cmd]
    return subprocess.run(
        cmd, check=check, capture_output=capture, text=True, timeout=timeout
    )


def scp_upload(cfg: dict, local_path: str, remote_path: str,
               check: bool = True) -> subprocess.CompletedProcess:
    """ローカルファイルをRunPodへアップロード"""
    target = f"{scp_target(cfg)}:{remote_path}"
    cmd = scp_base(cfg) + [str(local_path), target]
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def scp_download(cfg: dict, remote_path: str, local_path: str,
                 check: bool = True) -> subprocess.CompletedProcess:
    """RunPodからローカルへダウンロード"""
    source = f"{scp_target(cfg)}:{remote_path}"
    cmd = scp_base(cfg) + [source, str(local_path)]
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def ssh_check_alive(cfg: dict) -> bool:
    """SSH接続が生きているか確認"""
    try:
        r = ssh_run(cfg, "echo ok", check=False, timeout=15)
        return r.returncode == 0 and "ok" in r.stdout
    except (subprocess.TimeoutExpired, Exception):
        return False
