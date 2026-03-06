#!/bin/bash
# ============================================================
# RunPod 音声変換パイプライン クイックスタート
#
# 使い方:
#   ./start_runpod_pipeline.sh          # 全部まとめて起動
#   ./start_runpod_pipeline.sh sender   # sender のみ
#   ./start_runpod_pipeline.sh puller   # puller のみ
#   ./start_runpod_pipeline.sh worker   # RunPod ワーカー起動のみ
#   ./start_runpod_pipeline.sh check    # 接続確認のみ
#   ./start_runpod_pipeline.sh stop     # ワーカー停止
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# --- コマンド ---

do_check() {
    info "RunPod 接続確認..."
    python3 runpod_manager.py check
}

do_worker() {
    info "RunPod ワーカー デプロイ & 起動..."
    python3 runpod_manager.py run
}

do_sender() {
    info "Ubuntu sender 起動 (OSC /mixer 受信 → RunPod 転送)"
    info "Ctrl+C で停止"
    python3 ubuntu_sender.py
}

do_puller() {
    info "Ubuntu puller 起動 (RunPod → ローカル WAV 取得)"
    info "Ctrl+C で停止"
    python3 ubuntu_puller.py
}

do_stop() {
    info "RunPod ワーカー停止..."
    python3 runpod_manager.py stop
}

do_logs() {
    python3 runpod_manager.py logs
}

do_all() {
    info "============================================"
    info "RunPod 音声変換パイプライン フル起動"
    info "============================================"
    echo

    # Step 1: 接続確認
    do_check
    echo

    # Step 2: ワーカー起動
    do_worker
    echo

    # Step 3: sender & puller をバックグラウンドで起動
    info "sender & puller をバックグラウンドで起動..."

    python3 ubuntu_puller.py &
    PULLER_PID=$!
    info "puller 起動 (PID: $PULLER_PID)"

    # sender はフォアグラウンド (Ctrl+C で全終了)
    trap "info 'パイプライン停止中...'; kill $PULLER_PID 2>/dev/null; do_stop; info '完了'" EXIT

    info "sender 起動 (Ctrl+C で全停止)..."
    python3 ubuntu_sender.py
}

# --- メイン ---

case "${1:-all}" in
    check)  do_check ;;
    worker) do_worker ;;
    sender) do_sender ;;
    puller) do_puller ;;
    stop)   do_stop ;;
    logs)   do_logs ;;
    all)    do_all ;;
    *)
        echo "使い方: $0 {all|check|worker|sender|puller|stop|logs}"
        exit 1
        ;;
esac
