#!/bin/bash
# ============================================================
# Ubuntu (10.0.0.200) 側 venv 環境構築
#
# 使い方:
#   cd runpod/
#   bash setup_ubuntu_venv.sh
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

echo "[setup] Ubuntu RunPod パイプライン 環境構築"
echo "  ディレクトリ: $SCRIPT_DIR"
echo

# --- venv 作成 ---
if [ -d "$VENV_DIR" ]; then
    echo "[setup] 既存の venv を検出: $VENV_DIR"
    read -p "  再作成しますか? (y/N): " yn
    if [ "$yn" = "y" ] || [ "$yn" = "Y" ]; then
        rm -rf "$VENV_DIR"
        echo "[setup] 削除しました"
    else
        echo "[setup] 既存 venv を使用します"
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "[setup] venv 作成中..."
    python3 -m venv "$VENV_DIR"
    echo "[setup] ✅ venv 作成完了: $VENV_DIR"
fi

# --- activate & pip install ---
echo "[setup] パッケージインストール中..."
source "$VENV_DIR/bin/activate"

pip install --upgrade pip -q
pip install python-osc -q

echo
echo "[setup] ✅ セットアップ完了"
echo
echo "使い方:"
echo "  source $VENV_DIR/bin/activate"
echo "  python runpod_manager.py check"
echo "  ./start_runpod_pipeline.sh"
