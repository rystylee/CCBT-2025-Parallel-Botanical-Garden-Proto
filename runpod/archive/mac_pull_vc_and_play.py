#!/usr/bin/env python3
import json
import os
import time
import subprocess
from pathlib import Path

# ====== 設定（必要なら環境変数で上書き可）======
RUNPOD_USER = os.getenv("RUNPOD_USER", "root")
RUNPOD_HOST = os.getenv("RUNPOD_HOST", "194.68.245.46")
RUNPOD_PORT = int(os.getenv("RUNPOD_PORT", "22004"))
SSH_KEY = os.path.expanduser(os.getenv("SSH_KEY", "~/.ssh/id_ed25519"))

REMOTE_OUT_DIR = os.getenv("REMOTE_OUT_DIR", "/workspace/seed-vc/outputs")

LOCAL_DIR = Path(os.getenv(
    "LOCAL_DIR",
    "/Users/d21143/CODES/BI_M5_QwenSoftPrefix/vc_outputs"
)).expanduser()

POLL_SEC = float(os.getenv("POLL_SEC", "3"))      # 10秒に1回
STABLE_SEC = float(os.getenv("STABLE_SEC", "2"))   # 生成中回避（mtimeが2秒以上前のものだけ扱う）

AUDIO_EXTS = tuple(s.strip().lower() for s in os.getenv("AUDIO_EXTS", ".wav").split(","))

REMOVE_REMOTE = os.getenv("REMOVE_REMOTE", "0") == "1"

STATE_PATH = LOCAL_DIR / ".runpod_pull_state.json"

SSH_BASE = [
    "ssh", "-i", SSH_KEY, "-p", str(RUNPOD_PORT),
    "-o", "StrictHostKeyChecking=accept-new",
    f"{RUNPOD_USER}@{RUNPOD_HOST}",
]
SCP_BASE = [
    "scp", "-i", SSH_KEY, "-P", str(RUNPOD_PORT),
    "-o", "StrictHostKeyChecking=accept-new",
]


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def remote_list_files():
    """
    Runpod側で python で一覧を作って返す:
    NOW\t<epoch>
    <name>\t<size>\t<mtime>
    """
    remote_cmd = (
        "python3 - <<'PY'\n"
        "import time\n"
        "from pathlib import Path\n"
        f"out_dir = Path({REMOTE_OUT_DIR!r})\n"
        f"exts = {set(AUDIO_EXTS)!r}\n"
        "now = time.time()\n"
        "print('NOW\\t' + str(now))\n"
        "if out_dir.exists():\n"
        "    for p in sorted(out_dir.iterdir(), key=lambda x: x.stat().st_mtime):\n"
        "        if p.is_file() and p.suffix.lower() in exts:\n"
        "            st = p.stat()\n"
        "            print(p.name + '\\t' + str(st.st_size) + '\\t' + str(st.st_mtime))\n"
        "PY\n"
    )

    r = subprocess.run(SSH_BASE + [remote_cmd], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ssh list failed:\n{r.stderr}")

    lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    now = None
    files = []

    for ln in lines:
        if ln.startswith("NOW\t"):
            try:
                now = float(ln.split("\t", 1)[1])
            except Exception:
                now = None
            continue

        parts = ln.split("\t")
        if len(parts) != 3:
            continue
        name, size_s, mtime_s = parts
        try:
            size = int(size_s)
            mtime = float(mtime_s)
        except Exception:
            continue
        files.append({"name": name, "size": size, "mtime": mtime})

    if now is None:
        now = time.time()

    return now, files


def scp_download(remote_name: str, local_path: Path):
    remote_path = f"{RUNPOD_USER}@{RUNPOD_HOST}:{REMOTE_OUT_DIR}/{remote_name}"
    subprocess.run(SCP_BASE + [remote_path, str(local_path)], check=True)


def remote_remove(remote_name: str):
    cmd = f"rm -f {REMOTE_OUT_DIR}/{remote_name}"
    subprocess.run(SSH_BASE + [cmd], check=True)


def play_audio(local_path: Path):
    subprocess.run(["afplay", str(local_path)], check=True)


def main():
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()  # {"filename": {"size":..., "mtime":...}, ...}

    print("[MAC] polling Runpod outputs and auto-play")
    print(f"[MAC] Runpod: {RUNPOD_USER}@{RUNPOD_HOST}:{RUNPOD_PORT}  dir={REMOTE_OUT_DIR}")
    print(f"[MAC] Local: {LOCAL_DIR}")
    print(f"[MAC] poll={POLL_SEC}s  stable={STABLE_SEC}s  exts={AUDIO_EXTS}  remove_remote={REMOVE_REMOTE}")

    while True:
        try:
            now, files = remote_list_files()

            # 古い順に処理
            for info in files:
                name = info["name"]
                size = info["size"]
                mtime = info["mtime"]

                # 直近で更新されたものは生成中の可能性があるのでスキップ
                if (now - mtime) < STABLE_SEC:
                    continue

                prev = state.get(name)
                is_new_or_updated = (
                    prev is None or
                    prev.get("size") != size or
                    float(prev.get("mtime", 0)) != float(mtime)
                )
                if not is_new_or_updated:
                    continue

                local_path = LOCAL_DIR / name

                print(f"[MAC] NEW/UPDATED: {name}  (size={size}, mtime={mtime})")
                print(f"[MAC] downloading -> {local_path}")
                scp_download(name, local_path)

                print(f"[MAC] playing -> {local_path.name}")
                play_audio(local_path)

                state[name] = {"size": size, "mtime": mtime}
                save_state(state)

                if REMOVE_REMOTE:
                    remote_remove(name)
                    print(f"[MAC] removed remote: {name}")

        except Exception as e:
            print(f"[MAC] ERROR: {e}")

        time.sleep(POLL_SEC)


if __name__ == "__main__":
    main()
