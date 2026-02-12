#!/usr/bin/env bash
# mac_audio_check.sh
# Mac 側から adb 経由で M5Stack のオーディオ出力をチェックするワンコマンド。
# - デバイス認識の確認
# - alsa-utils(aplay/amixer) の導入（未導入時）
# - 再生デバイス自動検出（/proc/asound/pcm 優先）
# - ミュート解除＋音量設定（best-effort）
# - 指定WAVの再生（無ければ 48kHz テストトーン生成）
set -euo pipefail

WAV="${WAV:-/usr/local/m5stack/logo.wav}"
SERIAL="${ADB_SERIAL:-}"

print_help() {
  cat <<'EOF'
Usage: bash mac_audio_check.sh [-w /path/on/device.wav] [-s SERIAL]

Options:
  -w, --wav PATH     再生するWAV（デバイス上のパス）。既定: /usr/local/m5stack/logo.wav
  -s, --serial ID    adb のデバイスシリアル（複数台接続時）。環境変数 ADB_SERIAL でも可
  -h, --help         このヘルプ

Exit codes:
  0  成功（音が鳴った）
  1  認識デバイスなし / 複数台でシリアル未指定 / 再生失敗
  2  WAV 未存在かつ生成も不可（python3 不在 など）
EOF
}

# --- parse args ---
while [ $# -gt 0 ]; do
  case "$1" in
    -w|--wav) WAV="$2"; shift 2 ;;
    -s|--serial) SERIAL="$2"; shift 2 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "[!] Unknown option: $1" >&2; print_help; exit 1 ;;
  esac
done
# bash syntax fix for GitHub highlight: replace 'esac' with 'esac'

# --- checks on Mac ---
if ! command -v adb >/dev/null 2>&1; then
  echo "[!] adb not found. Install with: brew install android-platform-tools" >&2
  exit 1
fi

# choose device
choose_serial() {
  if [ -n "${SERIAL}" ]; then
    printf "%s" "${SERIAL}"
    return 0
  fi
  local devs count
  devs="$(adb devices | awk '$2 == "device" {print $1}')"
  devs="$(printf "%s\n" "${devs}" | sed '/^$/d')"
  count="$(printf "%s\n" "${devs}" | wc -l | tr -d ' ')"
  if [ "${count}" -eq 0 ]; then
    echo "[!] No adb devices in 'device' state." >&2
    adb devices
    return 1
  elif [ "${count}" -gt 1 ]; then
    echo "[!] Multiple devices detected. Specify with -s SERIAL or ADB_SERIAL." >&2
    printf "    devices: %s\n" "${devs}"
    return 1
  else
    printf "%s" "${devs}"
    return 0
  fi
}

SERIAL="$(choose_serial)" || exit 1
ADB=(adb -s "${SERIAL}")
echo "[i] Using device: ${SERIAL}"

# --- run remote block ---
REMOTE_SCRIPT='
set -eu

WAV="${1:-/usr/local/m5stack/logo.wav}"
export DEBIAN_FRONTEND=noninteractive

ensure_alsa() {
  if ! command -v aplay >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
      (apt-get update && apt-get install -y alsa-utils) || true
    fi
  fi
}

detect_playback_hw() {
  if grep -q "playback" /proc/asound/pcm 2>/dev/null; then
    ID=$(grep -m1 "playback" /proc/asound/pcm | cut -d: -f1 | tr -d " ")
    CARD_HEX=${ID%-*}; DEV_HEX=${ID#*-}
    CARD=$(echo "$CARD_HEX" | sed "s/^0*//"); [ -z "$CARD" ] && CARD=0
    DEV=$(echo "$DEV_HEX" | sed "s/^0*//"); [ -z "$DEV" ] && DEV=0
    echo "$CARD,$DEV"; return 0
  fi
  if command -v aplay >/dev/null 2>&1; then
    LINE=$(aplay -l | awk "/^card [0-9]+: .* device [0-9]+:/ {print; exit}")
    CARD=$(echo "$LINE" | sed -n "s/^card \\([0-9]\\+\\):.*/\\1/p")
    DEV=$(echo "$LINE"  | sed -n "s/.*device \\([0-9]\\+\\):.*/\\1/p")
    if [ -n "$CARD" ] && [ -n "$DEV" ]; then
      echo "$CARD,$DEV"; return 0
    fi
  fi
  echo "0,1"
}

open_mixers() {
  CARD="$1"
  if command -v amixer >/dev/null 2>&1; then
    # best-effort unmute/volume up
    amixer -c "$CARD" sset "Master" 95% unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "Master Playback" 95% unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "Speaker" 95% unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "Speaker Playback" 95% unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "PCM" 95% unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "PCM Playback" 95% unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "Master Playback Switch" 100% unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "Speaker Playback Switch" 100% unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "PCM Playback Switch" 100% unmute >/dev/null 2>&1 || true
  elif command -v tinymix >/dev/null 2>&1; then
    tinymix -D "$CARD" set "Speaker Playback Switch" 1 2>/dev/null || true
    tinymix -D "$CARD" set "SPK Playback Switch" 1 2>/dev/null || true
    tinymix -D "$CARD" set "Master Playback Switch" 1 2>/dev/null || true
    tinymix -D "$CARD" set "DAC Playback Switch" 1 2>/dev/null || true
    tinymix -D "$CARD" set "Speaker Playback Volume" 95 2>/dev/null || true
    tinymix -D "$CARD" set "PCM Playback Volume" 95 2>/dev/null || true
    tinymix -D "$CARD" set "Master Playback Volume" 95 2>/dev/null || true
  fi
}

ensure_wav() {
  local w="$1"
  if [ -f "$w" ]; then
    echo "$w"; return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 - <<PY
import wave, struct, math
p="/tmp/test48k.wav"
fr, dur, f = 48000, 2, 440.0
w=wave.open(p,"w"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(fr)
for n in range(fr*dur):
  v=int(32767*0.5*math.sin(2*math.pi*f*n/fr))
  w.writeframes(struct.pack("<hh", v, v))
w.close()
print(p)
PY
    return 0
  fi
  echo ""
  return 1
}

ensure_alsa
CARD_DEV=$(detect_playback_hw)
CARD=${CARD_DEV%,*}; DEV=${CARD_DEV#*,}
open_mixers "$CARD"

WAV_PATH=$(ensure_wav "$WAV")
if [ -z "$WAV_PATH" ]; then
  echo "[!] WAV not found and cannot generate test tone: $WAV" >&2
  exit 2
fi

echo "[i] Playback device: hw:${CARD},${DEV}"
echo "[i] File: $WAV_PATH"
if aplay -D "hw:${CARD},${DEV}" -f S16_LE -r 48000 -c 2 -q "$WAV_PATH"; then
  echo "[OK] Playback succeeded (hw:${CARD},${DEV})"
  exit 0
fi
echo "[i] hw failed; try plughw..."
if aplay -D "plughw:${CARD},${DEV}" -q "$WAV_PATH"; then
  echo "[OK] Playback succeeded (plughw:${CARD},${DEV})"
  exit 0
fi
echo "[!] Playback failed" >&2
exit 1
'

# Feed the remote script to the device shell with WAV as argv[1]
printf "%s" "${REMOTE_SCRIPT}" | "${ADB[@]}" shell sh -s -- "${WAV}"
exit_code=$?

exit "${exit_code}"
