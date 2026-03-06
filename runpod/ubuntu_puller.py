#!/usr/bin/env python3
"""RunPod → Ubuntu 結果取得 (VC出力WAVプル)

RunPod 上の Seed-VC 出力ディレクトリをポーリングし、
新しい WAV ファイルをローカルへダウンロードする。

使い方:
    python ubuntu_puller.py
    python ubuntu_puller.py --config runpod_config.json
    python ubuntu_puller.py --play   # ダウンロード後 aplay で再生
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from ssh_helper import load_config, ssh_run, scp_download


def remote_list_files(cfg: dict, remote_dir: str, extensions: set[str]) -> tuple[float, list[dict]]:
    """RunPod側のファイル一覧を取得 (Python経由で正確なmtimeを得る)"""
    remote_script = (
        f"python3 -c \""
        f"import time; from pathlib import Path; "
        f"d=Path('{remote_dir}'); "
        f"exts={extensions!r}; "
        f"now=time.time(); print('NOW\\\\t'+str(now)); "
        f"[print(p.name+'\\\\t'+str(p.stat().st_size)+'\\\\t'+str(p.stat().st_mtime)) "
        f"for p in sorted(d.iterdir(), key=lambda x: x.stat().st_mtime) "
        f"if p.is_file() and p.suffix.lower() in exts] "
        f"if d.exists() else None\""
    )

    r = ssh_run(cfg, remote_script, check=True, timeout=15)

    now = time.time()
    files = []

    for line in r.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("NOW\t"):
            try:
                now = float(line.split("\t", 1)[1])
            except Exception:
                pass
            continue

        parts = line.split("\t")
        if len(parts) != 3:
            continue
        name, size_s, mtime_s = parts
        try:
            files.append({"name": name, "size": int(size_s), "mtime": float(mtime_s)})
        except (ValueError, TypeError):
            continue

    return now, files


def remote_remove(cfg: dict, remote_dir: str, filename: str):
    """RunPod側のファイルを削除"""
    ssh_run(cfg, f"rm -f {remote_dir}/{filename}", check=False, timeout=10)


def play_audio(wav_path: Path):
    """ローカルで再生 (aplay / afplay)"""
    if sys.platform == "darwin":
        cmd = ["afplay", str(wav_path)]
    else:
        cmd = ["aplay", str(wav_path)]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
    except Exception as e:
        print(f"[puller] ⚠️  再生失敗: {e}")


def main():
    parser = argparse.ArgumentParser(description="RunPod → Ubuntu 結果取得")
    parser.add_argument("--config", default=None, help="設定ファイルパス")
    parser.add_argument("--play", action="store_true", help="ダウンロード後に再生")
    parser.add_argument("--once", action="store_true", help="1回だけ実行して終了")
    args = parser.parse_args()

    cfg = load_config(args.config)
    puller_cfg = cfg.get("ubuntu_puller", {})

    local_dir = Path(puller_cfg.get("local_output_dir", "./runpod_outputs")).expanduser()
    poll_sec = puller_cfg.get("poll_interval_sec", 3.0)
    stable_sec = puller_cfg.get("stable_sec", 2.0)
    extensions = set(puller_cfg.get("audio_extensions", [".wav"]))
    remove_remote = puller_cfg.get("remove_remote_after_pull", True)
    do_play = args.play or puller_cfg.get("play_on_pull", False)

    remote_dir = cfg["runpod"]["vc_out_dir"]

    local_dir.mkdir(parents=True, exist_ok=True)

    # 状態管理 (既知ファイルのsize+mtime)
    state_path = local_dir / ".puller_state.json"
    state: dict = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}

    def save_state():
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[puller] ============================")
    print(f"[puller] RunPod → Ubuntu 結果取得")
    print(f"[puller] リモート: {remote_dir}")
    print(f"[puller] ローカル: {local_dir}")
    print(f"[puller] poll={poll_sec}s  stable={stable_sec}s  remove={remove_remote}")
    print(f"[puller] ============================")

    while True:
        try:
            now, files = remote_list_files(cfg, remote_dir, extensions)

            for info in files:
                name = info["name"]
                size = info["size"]
                mtime = info["mtime"]

                # 生成中 (mtimeが直近) はスキップ
                if (now - mtime) < stable_sec:
                    continue

                # 既知ファイルとの差分チェック
                prev = state.get(name)
                if prev and prev.get("size") == size and prev.get("mtime") == mtime:
                    continue

                local_path = local_dir / name
                print(f"[puller] 新規/更新: {name} ({size} bytes)")

                try:
                    scp_download(cfg, f"{remote_dir}/{name}", str(local_path))
                    print(f"[puller] ✅ ダウンロード: {local_path}")

                    state[name] = {"size": size, "mtime": mtime}
                    save_state()

                    if do_play:
                        print(f"[puller] ▶ 再生中: {name}")
                        play_audio(local_path)

                    if remove_remote:
                        remote_remove(cfg, remote_dir, name)
                        print(f"[puller] 🗑  リモート削除: {name}")

                except Exception as e:
                    print(f"[puller] ❌ ダウンロード失敗: {name} → {e}")

        except Exception as e:
            print(f"[puller] ❌ ポーリングエラー: {e}")

        if args.once:
            break

        time.sleep(poll_sec)


if __name__ == "__main__":
    main()
