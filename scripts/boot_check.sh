#!/bin/bash
# =============================================================
#  CCBT BI Device - Boot Check Script
#  電源ON時に全機能チェックを自動実行し、ログを保存する
# =============================================================

set -euo pipefail

# --- 設定 ---
PROJECT_DIR="${CCBT_PROJECT_DIR:-/home/m5stack/CCBT-2025-Parallel-Botanical-Garden-Proto}"
LOG_DIR="${CCBT_LOG_DIR:-/var/log/ccbt-bi-check}"
MAX_LOG_FILES=30          # ログファイルの最大保持数
WAIT_SERVICES_TIMEOUT=120 # サービス起動待ちタイムアウト（秒）
CHECK_LANG="${CCBT_CHECK_LANG:-ja}"

# --- 依存サービス一覧 ---
# 必要に応じてコメントアウト/追加してください
REQUIRED_SERVICES=(
    "llm-llm"
    "llm-melotts"
    "llm-openai-api"
)

# --- ログ準備 ---
mkdir -p "${LOG_DIR}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="${LOG_DIR}/check_${TIMESTAMP}.log"
LATEST_LINK="${LOG_DIR}/latest.log"

# ログ関数（stdout + ファイル両方に出力）
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

# --- 古いログのローテーション ---
rotate_logs() {
    local count
    count=$(find "${LOG_DIR}" -name "check_*.log" -type f | wc -l)
    if [ "$count" -gt "$MAX_LOG_FILES" ]; then
        log "[LOG] ログローテーション: ${count}件 → ${MAX_LOG_FILES}件に削減"
        find "${LOG_DIR}" -name "check_*.log" -type f | sort | head -n $((count - MAX_LOG_FILES)) | xargs rm -f
    fi
}

# --- サービス起動待ち ---
wait_for_services() {
    log "[BOOT] 依存サービスの起動を待機中..."

    local start_time
    start_time=$(date +%s)

    for service in "${REQUIRED_SERVICES[@]}"; do
        log "[BOOT]   待機: ${service}"
        while true; do
            local elapsed=$(( $(date +%s) - start_time ))
            if [ "$elapsed" -ge "$WAIT_SERVICES_TIMEOUT" ]; then
                log "[WARN] サービス待機タイムアウト (${WAIT_SERVICES_TIMEOUT}秒): ${service}"
                log "[WARN] タイムアウトしたサービスがありますが、チェックを続行します"
                return 1
            fi

            if systemctl is-active --quiet "${service}" 2>/dev/null; then
                log "[BOOT]   ✓ ${service} (起動済み)"
                break
            fi

            sleep 2
        done
    done

    log "[BOOT] 全サービス起動確認完了"
    return 0
}

# --- メイン処理 ---
main() {
    log "============================================================"
    log "  CCBT BI デバイス起動時チェック"
    log "  Timestamp: ${TIMESTAMP}"
    log "  Log file:  ${LOG_FILE}"
    log "============================================================"

    # プロジェクトディレクトリ確認
    if [ ! -d "${PROJECT_DIR}" ]; then
        log "[ERROR] プロジェクトディレクトリが見つかりません: ${PROJECT_DIR}"
        exit 1
    fi

    if [ ! -f "${PROJECT_DIR}/scripts/check_all.py" ]; then
        log "[ERROR] check_all.py が見つかりません: ${PROJECT_DIR}/scripts/check_all.py"
        exit 1
    fi

    cd "${PROJECT_DIR}"

    # サービス起動待ち
    wait_for_services || true

    # 少し余裕を持たせる（サービスの内部初期化待ち）
    log "[BOOT] サービス安定待ち (5秒)..."
    sleep 5

    # チェック実行
    log "[BOOT] チェック開始..."
    local exit_code=0

    # uv が使えれば uv run、なければ直接 python3
    if command -v uv &>/dev/null; then
        uv run python scripts/check_all.py --lang "${CHECK_LANG}" --play-tts 2>&1 | tee -a "${LOG_FILE}" || exit_code=$?
    else
        python3 scripts/check_all.py --lang "${CHECK_LANG}" --play-tts 2>&1 | tee -a "${LOG_FILE}" || exit_code=$?
    fi

    # 結果記録
    log ""
    if [ "$exit_code" -eq 0 ]; then
        log "[BOOT] ====== 全チェック OK ✓ ======"
    else
        log "[BOOT] ====== チェック失敗あり (exit code: ${exit_code}) ======"
    fi
    log "[BOOT] ログ保存先: ${LOG_FILE}"

    # latest シンボリックリンク更新
    ln -sf "${LOG_FILE}" "${LATEST_LINK}"

    # ログローテーション
    rotate_logs

    exit ${exit_code}
}

main "$@"
