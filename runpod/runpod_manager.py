#!/usr/bin/env python3
"""RunPod マネージャー

RunPod インスタンスへの接続確認・環境セットアップ・コードデプロイ・ワーカー起動を管理する。

使い方:
    # 接続確認
    python runpod_manager.py check

    # 環境構築 (MeloTTS + Seed-VC のインストール)
    python runpod_manager.py setup

    # ワーカースクリプトをデプロイ
    python runpod_manager.py deploy

    # ワーカー起動 (バックグラウンド tmux セッション)
    python runpod_manager.py start

    # ワーカー停止
    python runpod_manager.py stop

    # ワーカーのログ確認
    python runpod_manager.py logs

    # 全部まとめて: 接続確認 → デプロイ → 起動
    python runpod_manager.py run
"""

import argparse
import sys
import time
from pathlib import Path

from ssh_helper import load_config, ssh_run, scp_upload, ssh_check_alive

TMUX_SESSION = "voice_worker"


def cmd_check(cfg: dict) -> bool:
    """SSH接続とGPU状態を確認"""
    print("[check] SSH接続テスト...")
    if not ssh_check_alive(cfg):
        print("[check] ❌ SSH接続失敗。RunPodが起動しているか確認してください。")
        return False
    print("[check] ✅ SSH接続OK")

    # GPU確認
    print("[check] GPU状態...")
    try:
        r = ssh_run(cfg, "nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader", timeout=15)
        for line in r.stdout.strip().splitlines():
            print(f"  GPU: {line.strip()}")
    except Exception as e:
        print(f"[check] ⚠️  GPU情報取得失敗 (CPU-onlyの可能性): {e}")

    # ディスク確認
    try:
        r = ssh_run(cfg, "df -h /workspace | tail -1", timeout=10)
        print(f"  Disk: {r.stdout.strip()}")
    except Exception:
        pass

    # 既存環境確認
    rp = cfg["runpod"]
    checks = {
        "Seed-VC": rp["seed_vc_dir"],
        "MeloTTS": rp["melo_dir"],
        "target_audio": rp["target_audio"],
    }
    for name, path in checks.items():
        try:
            r = ssh_run(cfg, f"test -e {path} && echo EXISTS || echo MISSING", timeout=10)
            status = r.stdout.strip()
            mark = "✅" if status == "EXISTS" else "❌"
            print(f"  {mark} {name}: {path}")
        except Exception:
            print(f"  ❓ {name}: {path} (確認失敗)")

    return True


def cmd_setup(cfg: dict):
    """RunPod環境構築 (MeloTTS + Seed-VC)"""
    rp = cfg["runpod"]

    print("[setup] MeloTTS インストール...")
    melo_script = f"""
set -e
cd {rp['workspace']}
if [ ! -d MeloTTS ]; then
    git clone https://github.com/myshell-ai/MeloTTS.git
    cd MeloTTS
    pip install -q -e .
    python -m unidic download
    echo "[setup] MeloTTS installed"
else
    echo "[setup] MeloTTS already exists, skipping"
fi
"""
    r = ssh_run(cfg, melo_script, check=False, timeout=600)
    print(r.stdout)
    if r.stderr:
        print(r.stderr, file=sys.stderr)

    print("[setup] Seed-VC インストール...")
    seedvc_script = f"""
set -e
cd {rp['workspace']}
if [ ! -d seed-vc ]; then
    git clone https://github.com/Plachtaa/seed-vc.git
    cd seed-vc
    pip install -r requirements.txt
    pip uninstall tensorflow -y 2>/dev/null || true
    echo "[setup] Seed-VC installed"
else
    echo "[setup] Seed-VC already exists, skipping"
fi
"""
    r = ssh_run(cfg, seedvc_script, check=False, timeout=600)
    print(r.stdout)
    if r.stderr:
        print(r.stderr, file=sys.stderr)

    # ディレクトリ作成
    dirs = [rp["osc_json_dir"], rp["tts_out_dir"], rp["vc_out_dir"], rp.get("audio_dir", "/workspace/audio")]
    ssh_run(cfg, f"mkdir -p {' '.join(dirs)}", check=False, timeout=10)

    # target_audio存在確認
    r = ssh_run(cfg, f"test -f {rp['target_audio']} && echo OK || echo MISSING", timeout=10)
    if "MISSING" in r.stdout:
        print(f"[setup] ⚠️  target_audio が見つかりません: {rp['target_audio']}")
        print(f"         nainiku.mp3 を RunPod へ手動アップロードしてください:")
        print(f"         scp -i ~/.ssh/id_ed25519 audio/nainiku.mp3 {cfg['ssh']['user']}@{cfg['ssh']['host']}:{rp['target_audio']}")

    print("[setup] ✅ セットアップ完了")


def cmd_deploy(cfg: dict):
    """ワーカースクリプトをRunPodへデプロイ"""
    rp = cfg["runpod"]
    local_dir = Path(__file__).parent

    # デプロイ対象ファイル
    files_to_deploy = [
        ("runpod_a_make_voice.py", rp["worker_script"]),
    ]

    for local_name, remote_path in files_to_deploy:
        local_path = local_dir / local_name
        if not local_path.exists():
            print(f"[deploy] ⚠️  {local_name} が見つかりません、スキップ")
            continue
        print(f"[deploy] {local_name} → {remote_path}")
        scp_upload(cfg, str(local_path), remote_path)

    print("[deploy] ✅ デプロイ完了")


def cmd_start(cfg: dict):
    """ワーカーをtmuxセッションで起動"""
    rp = cfg["runpod"]

    # 既存セッション確認
    r = ssh_run(cfg, f"tmux has-session -t {TMUX_SESSION} 2>/dev/null && echo RUNNING || echo STOPPED",
                check=False, timeout=10)
    if "RUNNING" in r.stdout:
        print(f"[start] ⚠️  tmuxセッション '{TMUX_SESSION}' は既に起動中です")
        print(f"         停止: python runpod_manager.py stop")
        print(f"         ログ: python runpod_manager.py logs")
        return

    # 環境変数を設定してワーカー起動
    env_vars = (
        f"OSC_JSON_DIR={rp['osc_json_dir']} "
        f"DRIVE_PATH={rp['seed_vc_dir']} "
        f"TTS_DIR={rp['tts_out_dir']} "
        f"OUT_DIR={rp['vc_out_dir']} "
        f"TARGET_AUDIO={rp['target_audio']} "
        f"INFER_SCRIPT={rp['seed_vc_dir']}/inference_v2.py "
    )

    start_cmd = (
        f"tmux new-session -d -s {TMUX_SESSION} "
        f"'{env_vars} python3 {rp['worker_script']} 2>&1 | tee /workspace/voice_worker.log'"
    )

    print(f"[start] ワーカー起動中...")
    ssh_run(cfg, start_cmd, check=True, timeout=15)

    # 起動確認
    time.sleep(2)
    r = ssh_run(cfg, f"tmux has-session -t {TMUX_SESSION} 2>/dev/null && echo RUNNING || echo STOPPED",
                check=False, timeout=10)
    if "RUNNING" in r.stdout:
        print(f"[start] ✅ ワーカー起動成功 (tmux: {TMUX_SESSION})")
    else:
        print(f"[start] ❌ ワーカー起動失敗。ログを確認してください:")
        print(f"         python runpod_manager.py logs")


def cmd_stop(cfg: dict):
    """ワーカー停止"""
    print(f"[stop] tmuxセッション '{TMUX_SESSION}' を停止...")
    ssh_run(cfg, f"tmux kill-session -t {TMUX_SESSION} 2>/dev/null || true", check=False, timeout=10)
    print("[stop] ✅ 停止完了")


def cmd_logs(cfg: dict):
    """ワーカーログ表示 (最新50行)"""
    print(f"[logs] ワーカーログ (最新50行):")
    print("=" * 60)
    r = ssh_run(cfg, "tail -50 /workspace/voice_worker.log 2>/dev/null || echo '(ログなし)'",
                check=False, timeout=10)
    print(r.stdout)


def cmd_run(cfg: dict):
    """接続確認 → デプロイ → 起動 を一括実行"""
    if not cmd_check(cfg):
        sys.exit(1)
    print()
    cmd_deploy(cfg)
    print()
    cmd_start(cfg)


def main():
    parser = argparse.ArgumentParser(description="RunPod マネージャー")
    parser.add_argument("command", choices=["check", "setup", "deploy", "start", "stop", "logs", "run"],
                        help="実行するコマンド")
    parser.add_argument("--config", default=None, help="設定ファイルパス (デフォルト: runpod_config.json)")
    args = parser.parse_args()

    cfg = load_config(args.config)

    commands = {
        "check": cmd_check,
        "setup": cmd_setup,
        "deploy": cmd_deploy,
        "start": cmd_start,
        "stop": cmd_stop,
        "logs": cmd_logs,
        "run": cmd_run,
    }

    commands[args.command](cfg)


if __name__ == "__main__":
    main()
