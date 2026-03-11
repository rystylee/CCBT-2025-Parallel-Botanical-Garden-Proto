#!/bin/bash

################################################################################
# BI Audio Check Upload Script
#
# Purpose: Upload audio check files to all BI devices (10.0.0.1 - 10.0.0.100)
# - Maps bi_check_XXX.wav to corresponding IP 10.0.0.XXX
# - Uploads to /usr/local/m5stack/audio_check.wav on each BI
# - Parallel execution: 10 devices at a time
# - Auto-retry: up to 3 attempts per device
# - Logging: success/failure logged to logs/ directory
################################################################################

set -euo pipefail

# Configuration
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AUDIO_DIR="${BASE_DIR}/bi_audio_check"
LOG_DIR="${BASE_DIR}/logs"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="${LOG_DIR}/upload_audio_check_${TIMESTAMP}.log"

# SSH Configuration
SSH_USER="root"
SSH_PASS="root"
TARGET_PATH="/usr/local/m5stack/audio_check.wav"

# Execution parameters
MAX_RETRIES=3
PARALLEL_COUNT=10
TOTAL_DEVICES=100

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Create log directory if not exists
mkdir -p "${LOG_DIR}"

# Check if sshpass is installed
if ! command -v sshpass &> /dev/null; then
    echo -e "${RED}Error: sshpass is not installed${NC}"
    echo "Please install sshpass:"
    echo "  macOS: brew install sshpass"
    echo "  Ubuntu/Debian: sudo apt-get install sshpass"
    exit 1
fi

# Initialize counters
declare -a SUCCESS_LIST
declare -a FAILED_LIST
PROCESSED=0

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_FILE}"
}

# Upload function for a single device
upload_to_device() {
    local device_num=$1
    local ip="10.0.0.${device_num}"
    local audio_file="${AUDIO_DIR}/bi_check_$(printf '%03d' ${device_num}).wav"

    # Check if audio file exists
    if [[ ! -f "${audio_file}" ]]; then
        log "ERROR: Audio file not found: ${audio_file}"
        return 1
    fi

    # Retry logic
    local attempt=1
    while [[ ${attempt} -le ${MAX_RETRIES} ]]; do
        if sshpass -p "${SSH_PASS}" scp \
            -o StrictHostKeyChecking=no \
            -o UserKnownHostsFile=/dev/null \
            -o ConnectTimeout=10 \
            -o LogLevel=ERROR \
            "${audio_file}" \
            "${SSH_USER}@${ip}:${TARGET_PATH}" >> "${LOG_FILE}" 2>&1; then

            log "SUCCESS: ${ip} (bi_check_$(printf '%03d' ${device_num}).wav) - Attempt ${attempt}"
            return 0
        else
            if [[ ${attempt} -lt ${MAX_RETRIES} ]]; then
                log "RETRY: ${ip} - Attempt ${attempt} failed, retrying..."
                sleep 2
            fi
            ((attempt++))
        fi
    done

    log "FAILED: ${ip} (bi_check_$(printf '%03d' ${device_num}).wav) - All ${MAX_RETRIES} attempts failed"
    return 1
}

# Export function for parallel execution
export -f upload_to_device
export -f log
export SSH_USER SSH_PASS TARGET_PATH AUDIO_DIR LOG_FILE MAX_RETRIES

# Main execution
log "========================================="
log "BI Audio Check Upload Started"
log "========================================="
log "Total devices: ${TOTAL_DEVICES}"
log "Parallel execution: ${PARALLEL_COUNT} devices at a time"
log "Max retries per device: ${MAX_RETRIES}"
log "Log file: ${LOG_FILE}"
log "========================================="

echo -e "${YELLOW}Starting upload to ${TOTAL_DEVICES} BI devices...${NC}"

# Process devices in batches
for ((batch_start=1; batch_start<=TOTAL_DEVICES; batch_start+=PARALLEL_COUNT)); do
    batch_end=$((batch_start + PARALLEL_COUNT - 1))
    if [[ ${batch_end} -gt ${TOTAL_DEVICES} ]]; then
        batch_end=${TOTAL_DEVICES}
    fi

    echo -e "${YELLOW}Processing batch: ${batch_start}-${batch_end}${NC}"

    # Run parallel uploads for this batch
    for ((i=batch_start; i<=batch_end; i++)); do
        (
            if upload_to_device ${i}; then
                echo "SUCCESS:${i}"
            else
                echo "FAILED:${i}"
            fi
        ) &
    done

    # Wait for this batch to complete
    wait

    # Update progress
    PROCESSED=${batch_end}
    echo -e "${GREEN}Progress: ${PROCESSED}/${TOTAL_DEVICES} devices processed${NC}"
done

# Parse results from log file
SUCCESS_COUNT=$(grep -c "^SUCCESS:" "${LOG_FILE}" || true)
FAILED_COUNT=$(grep -c "^FAILED:" "${LOG_FILE}" || true)

# Generate summary
log "========================================="
log "Upload Summary"
log "========================================="
log "Total devices: ${TOTAL_DEVICES}"
log "Successful: ${SUCCESS_COUNT}"
log "Failed: ${FAILED_COUNT}"
log "========================================="

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Upload Complete${NC}"
echo -e "${GREEN}=========================================${NC}"
echo -e "Total devices: ${TOTAL_DEVICES}"
echo -e "${GREEN}Successful: ${SUCCESS_COUNT}${NC}"
echo -e "${RED}Failed: ${FAILED_COUNT}${NC}"
echo -e "Log file: ${LOG_FILE}"
echo -e "${GREEN}=========================================${NC}"

# Show failed devices if any
if [[ ${FAILED_COUNT} -gt 0 ]]; then
    echo ""
    echo -e "${RED}Failed devices:${NC}"
    grep "^FAILED:" "${LOG_FILE}" | while read -r line; do
        device_num=$(echo "${line}" | grep -oP '10\.0\.0\.\K\d+')
        echo -e "${RED}  - 10.0.0.${device_num} (bi_check_$(printf '%03d' ${device_num}).wav)${NC}"
    done
fi

# Exit with error if any uploads failed
if [[ ${FAILED_COUNT} -gt 0 ]]; then
    exit 1
fi

exit 0
