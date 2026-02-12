\
#!/usr/bin/env bash
# mac_tts_stackflow_smoke.sh — StackFlow TTS + ALSA + playing flag + loop & volume + WAV attenuation (fixed here-doc args)
set -euo pipefail

LANG_SEL=""
SERIAL="${ADB_SERIAL:-}"
TEXT_OVERRIDE=""
ALSA_DEVICE="${ALSA_DEVICE:-}"  # e.g. "hw:0,1" or "plughw:0,1"
LOOP_FLAG=0
VOL_PCT="95"
GAIN_LIN=""    # 0.0..1.0
GAIN_DB=""     # e.g. -12

print_help() {
  cat <<'EOF'
Usage: bash mac_tts_stackflow_smoke.sh -l JP|EN|CN|FR [-t "text"] [-s SERIAL] [-L] [-V 0-100] [-g 0.0-1.0|-d -60..+20]

Options:
  -l LANG     言語（JP|EN|CN|FR）
  -t "TEXT"   読み上げるテキスト（未指定: 言語別の既定文）
  -s SERIAL   adb デバイス（複数台接続時）
  -L          ループ再生（Ctrl-C で停止）
  -V 0-100    ミキサ音量（既定 95）※ボードにより効かない場合あり
  -g 0.0-1.0  WAV 線形ゲイン（0.3 ≒ -10.5 dB）
  -d dB       WAV dB 指定（例: -12）
  -h          ヘルプ

Env:
  ALSA_DEVICE    再生デバイス（例: hw:0,1 / plughw:0,1）
  STACKFLOW_BASE OpenAI互換APIベースURL（既定 http://127.0.0.1:8000/v1）
  TTS_SPEED      合成速度（既定 1.0）
EOF
}

# --- parse args ---
while [ $# -gt 0 ]; do
  case "$1" in
    -l) LANG_SEL="$2"; shift 2 ;;
    -t) TEXT_OVERRIDE="$2"; shift 2 ;;
    -s) SERIAL="$2"; shift 2 ;;
    -L) LOOP_FLAG=1; shift 1 ;;
    -V) VOL_PCT="$2"; shift 2 ;;
    -g) GAIN_LIN="$2"; shift 2 ;;
    -d) GAIN_DB="$2";  shift 2 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "[!] Unknown option: $1" >&2; print_help; exit 1 ;;
  esac
done

[ -n "${LANG_SEL}" ] || { echo "[!] -l JP|EN|CN|FR を指定してください" >&2; exit 1; }

command -v adb >/dev/null 2>&1 || { echo "[!] adb not found. brew install android-platform-tools" >&2; exit 1; }

# --- choose device ---
choose_serial() {
  if [ -n "${SERIAL}" ]; then printf "%s" "${SERIAL}"; return 0; fi
  local devs count
  devs="$(adb devices | awk '$2 == "device" {print $1}')" ; devs="$(printf "%s\n" "$devs" | sed '/^$/d')"
  count="$(printf "%s\n" "$devs" | wc -l | tr -d ' ')"
  if [ "$count" -eq 0 ]; then echo "[!] No adb devices in 'device' state." >&2; adb devices; return 1; fi
  if [ "$count" -gt 1 ]; then echo "[!] Multiple devices. Use -s SERIAL or ADB_SERIAL." >&2; printf "devices:\n%s\n" "$devs"; return 1; fi
  printf "%s" "$devs"
}
SERIAL="$(choose_serial)" || exit 1
ADB=(adb -s "${SERIAL}")
echo "[i] Using device: ${SERIAL}"

# --- default texts ---
case "$(echo "${LANG_SEL}" | tr '[:lower:]' '[:upper:]')" in
  JP) SAMPLE_TEXT="ご来場ありがとうございます。本展示をゆっくりお楽しみください。" ;;
  EN) SAMPLE_TEXT="Welcome and thank you for visiting. Please enjoy the exhibition." ;;
  CN) SAMPLE_TEXT="欢迎您的到来。祝您参观愉快。" ;;
  FR) SAMPLE_TEXT="Bienvenue et merci de votre visite. Profitez bien de l'exposition." ;;
  *)  echo "[!] Unsupported language: ${LANG_SEL}" >&2; exit 1 ;;
esac
TEXT="${TEXT_OVERRIDE:-$SAMPLE_TEXT}"

# --- create remote script (PTY-safe) ---
REMOTE_LOCAL="$(mktemp -t tts_stackflow_remote.XXXXXX.sh)"
cat > "${REMOTE_LOCAL}" <<'EOS'
#!/bin/sh
# /tmp/tts_stackflow_remote.sh — runs on device
set -eu

LANG_SEL="${1:-}"
TEXT_B64="${2:-}"
ALSA_ARG="${3:-__NONE__}"   # "__NONE__" sentinel
VOL_PCT_IN="${4:-95}"
LOOP_FLAG="${5:-0}"
GAIN_LIN_IN="${6:-__NONE__}"
GAIN_DB_IN="${7:-__NONE__}"

[ -n "$LANG_SEL" ] && [ -n "$TEXT_B64" ] || { echo "[!] missing arguments"; exit 2; }

# decode text
if command -v base64 >/dev/null 2>&1; then TEXT="$(printf %s "$TEXT_B64" | base64 -d 2>/dev/null || printf %s "$TEXT_B64")"; else TEXT="$TEXT_B64"; fi
# ALSA device
[ "$ALSA_ARG" = "__NONE__" ] && ALSA_DEVICE="" || ALSA_DEVICE="$ALSA_ARG"

# volume sanitize
case "$VOL_PCT_IN" in ''|*[!0-9]*) VOL_PCT="95";; *) VOL_PCT="$VOL_PCT_IN";; esac
[ "$VOL_PCT" -gt 100 ] && VOL_PCT=100; [ "$VOL_PCT" -lt 0 ] && VOL_PCT=0

# gain select
GAIN_MODE="none"; GAIN_VAL="1.0"
if [ "$GAIN_DB_IN" != "__NONE__" ] && [ -n "$GAIN_DB_IN" ]; then
  GAIN_VAL="$(python3 - "$GAIN_DB_IN" <<'PY'
import math,sys
try:
  db=float(sys.argv[1]); print(10**(db/20.0))
except Exception:
  print(1.0)
PY
)"
  GAIN_MODE="db"
elif [ "$GAIN_LIN_IN" != "__NONE__" ] && [ -n "$GAIN_LIN_IN" ]; then
  GAIN_VAL="$GAIN_LIN_IN"; GAIN_MODE="lin"
fi
# clamp via python (0.0..3.0)
if ! python3 - "$GAIN_VAL" <<'PY' >/dev/null 2>&1
import sys
try:
  g=float(sys.argv[1]); assert 0.0 <= g <= 3.0
except Exception:
  raise SystemExit(1)
PY
then
  GAIN_VAL="1.0"; GAIN_MODE="none"
fi

OUT="/tmp/tts_${LANG_SEL}.wav"
OUT_GAIN="/tmp/tts_${LANG_SEL}_gain.wav"
OUT_RES="/tmp/tts_${LANG_SEL}_48k_stereo.wav"
OUT_RES_GAIN="/tmp/tts_${LANG_SEL}_48k_stereo_gain.wav"
STATUS="/tmp/tts_status.json"
LOG="/tmp/tts_stackflow.log"

need() { command -v "$1" >/dev/null 2>&1; }
log(){ printf "%s\n" "$*" | tee -a "$LOG" >/dev/null; }

ensure_pkgs() { if need apt-get; then apt-get update >>"$LOG" 2>&1 || true; apt-get install -y alsa-utils curl jq python3 >>"$LOG" 2>&1 || true; fi; }

detect_hw() {
  if grep -q "playback" /proc/asound/pcm 2>/dev/null; then
    ID="$(grep -m1 "playback" /proc/asound/pcm | cut -d: -f1 | tr -d " ")"
    CARD_HEX="${ID%-*}"; DEV_HEX="${ID#*-}"
    CARD="$(echo "$CARD_HEX" | sed 's/^0*//')"; [ -z "$CARD" ] && CARD=0
    DEV="$(echo "$DEV_HEX" | sed 's/^0*//')"; [ -z "$DEV" ] && DEV=0
    echo "${CARD},${DEV}"; return 0
  fi
  echo "0,1"
}

open_mixers() {
  CARD="$1"; VOL="$2"
  if need amixer; then
    amixer -c "$CARD" sset "Master"    "${VOL}%" unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "Speaker"   "${VOL}%" unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "PCM"       "${VOL}%" unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "Headphone" "${VOL}%" unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "Master Playback Switch"  100% unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "Speaker Playback Switch" 100% unmute >/dev/null 2>&1 || true
    amixer -c "$CARD" sset "PCM Playback Switch"     100% unmute >/dev/null 2>&1 || true
  elif need tinymix; then
    # more candidates
    for sw in "Speaker Playback Switch" "SPK Playback Switch" "Master Playback Switch" "DAC Playback Switch"; do
      tinymix -D "$CARD" set "$sw" 1 2>/dev/null || true
    done
    for vol in "Speaker Playback Volume" "SPK Playback Volume" "PCM Playback Volume" "Master Playback Volume" "DAC Playback Volume" "DAC Digital Volume"; do
      tinymix -D "$CARD" set "$vol" "$VOL" 2>/dev/null || true
    done
  fi
}

# language -> model
first_model=""; second_model=""; first_pkg=""; second_pkg=""
case "$(echo "$LANG_SEL" | tr '[:lower:]' '[:upper:]')" in
  JP) first_model="melotts-ja-jp"; first_pkg="llm-model-melotts-ja-jp" ;;
  EN) first_model="melotts-en-us"; first_pkg="llm-model-melotts-en-us"; second_model="melotts-en-default"; second_pkg="llm-model-melotts-en-default" ;;
  CN) first_model="melotts-zh-cn"; first_pkg="llm-model-melotts-zh-cn" ;;
  FR) first_model="melotts-fr-fr"; first_pkg="llm-model-melotts-fr-fr"; second_model="melotts-en-us"; second_pkg="llm-model-melotts-en-us" ;;
  *)  first_model="melotts-en-us"; first_pkg="llm-model-melotts-en-us" ;;
esac
BASE_URL="${STACKFLOW_BASE:-http://127.0.0.1:8000/v1}"
SPEED="${TTS_SPEED:-1.0}"

ensure_model_active() {
  target="$1"; pkg="$2"
  if need curl; then
    if curl -fsS "${BASE_URL}/models" >/dev/null 2>&1; then
      if curl -fsS "${BASE_URL}/models" | grep -q "\"id\": *\"$target\""; then echo "OK"; return 0; fi
    fi
  fi
  if [ -n "$pkg" ] && need apt-get; then
    log "[i] apt install $pkg"; apt-get install -y "$pkg" >>"$LOG" 2>&1 || true
    if command -v systemctl >/dev/null 2>&1; then systemctl restart llm-openai-api >>"$LOG" 2>&1 || true; sleep 2; fi
    if curl -fsS "${BASE_URL}/models" | grep -q "\"id\": *\"$target\""; then echo "OK"; return 0; fi
  fi
  echo "NG"; return 1
}
choose_model() {
  [ -n "$first_model" ] && [ "$(ensure_model_active "$first_model" "$first_pkg" || echo NG)" = "OK" ] && { echo "$first_model"; return; }
  [ -n "$second_model" ] && [ "$(ensure_model_active "$second_model" "$second_pkg" || echo NG)" = "OK" ] && { echo "$second_model"; return; }
  echo "$first_model"
}

gen_tts_wav() {
  model="$1"; text="$2"; outfile="$3"
  REQ="/tmp/tts_req_${LANG_SEL}_$$.json"; RESP="/tmp/tts_resp_${LANG_SEL}_$$.bin"
  MODEL_ENV="$model" TEXT_ENV="$text" SPEED_ENV="$SPEED" python3 - <<'PY' >"$REQ"
import json, os
payload={"model":os.environ.get("MODEL_ENV",""),"input":os.environ.get("TEXT_ENV",""),
         "response_format":"wav","speed":float(os.environ.get("SPEED_ENV","1.0") or "1.0")}
print(json.dumps(payload, ensure_ascii=False))
PY
  HTTP="$(curl -sS -o "$RESP" -w "%{http_code}" -X POST "${BASE_URL}/audio/speech" \
          -H "Content-Type: application/json" -H "Authorization: Bearer sk-local" \
          --data-binary @"$REQ" || echo "000")"
  if [ "$HTTP" = "200" ] || [ "$HTTP" = "201" ]; then mv "$RESP" "$outfile"; rm -f "$REQ"; [ -s "$outfile" ] || return 1; return 0; fi
  echo "[!] speech API failed (HTTP=$HTTP)" | tee -a "$LOG" >/dev/null
  echo "[resp] ---- begin ----" >>"$LOG"; head -c 800 "$RESP" | sed 's/^/[resp] /' >>"$LOG" || true; echo >>"$LOG"; echo "[resp] ----  end  ----" >>"$LOG"
  rm -f "$REQ" "$RESP"; return 1
}

apply_gain() {
  IN="$1"; OUT="$2"; G="$3"
  [ "$G" = "1.0" ] && { cp -f "$IN" "$OUT"; return 0; }
  python3 - "$IN" "$OUT" "$G" <<'PY' || true
import wave, sys, audioop
src, dst, gain = sys.argv[1], sys.argv[2], float(sys.argv[3])
with wave.open(src, 'rb') as r:
    nchan=r.getnchannels(); sw=r.getsampwidth(); fr=r.getframerate()
    frames=r.readframes(r.getnframes())
if sw!=2: frames=audioop.lin2lin(frames, sw, 2); sw=2
frames=audioop.mul(frames, 2, gain)
with wave.open(dst,'wb') as w:
    w.setnchannels(nchan); w.setsampwidth(2); w.setframerate(fr); w.writeframes(frames)
PY
  [ -s "$OUT" ]
}

resample_to_48k_stereo() {
  IN="$1"; OUT="$2"
  python3 - "$IN" "$OUT" <<'PY' || true
import wave, sys, audioop
src, dst = sys.argv[1], sys.argv[2]
with wave.open(src,'rb') as r:
  fr=r.getframerate(); ch=r.getnchannels(); sw=r.getsampwidth(); frames=r.readframes(r.getnframes())
if sw!=2: frames=audioop.lin2lin(frames, sw, 2); sw=2
if ch>2: frames=audioop.tomono(frames,2,0.5,0.5); ch=1
if ch==1: frames=audioop.tostereo(frames,2,1.0,1.0); ch=2
if fr!=48000: frames,_=audioop.ratecv(frames,2,ch,fr,48000,None); fr=48000
with wave.open(dst,'wb') as w:
  w.setnchannels(ch); w.setsampwidth(2); w.setframerate(fr); w.writeframes(frames)
PY
  [ -s "$OUT" ]
}

write_status() {
  playing="$1"; started="$2"; ended="$3"; lang="$4"; model="$5"; text="$6"; pid="$7"; file="$8"
  { printf '{'; printf '"playing": %s' "$playing"
    [ -n "$started" ] && printf ', "started_at": %s' "$started"
    [ -n "$ended"   ] && printf ', "ended_at": %s'   "$ended"
    printf ', "lang": "%s", "model": "%s", ' "$lang" "$model"
    esc=$(printf "%s" "$text" | sed 's/\\/\\\\/g; s/"/\\"/g')
    printf '"text": "%s", ' "$esc"
    [ -n "$pid" ] && printf '"pid": %s, ' "$pid"
    printf '"file": "%s"}\n' "$file"; } > "$STATUS"
}

play_once() {
  devspec="$1"; wav="$2"; rate="$3"; ch="$4"
  started="$(date +%s)"
  if [ -n "$rate" ] && [ -n "$ch" ] && echo "$devspec" | grep -q '^hw:'; then aplay -D "$devspec" -f S16_LE -r "$rate" -c "$ch" -q "$wav" & else aplay -D "$devspec" -q "$wav" & fi
  APID=$!; write_status true "$started" "" "$LANG_SEL" "$MODEL" "$TEXT" "$APID" "$wav"
  set +e; wait "$APID"; EC=$?; set -e
  ended="$(date +%s)"; write_status false "$started" "$ended" "$LANG_SEL" "$MODEL" "$TEXT" "$APID" "$wav"
  return "$EC"
}

main() {
  ensure_pkgs
  CARD_DEV="$(detect_hw)"; CARD="${CARD_DEV%,*}"; DEV="${CARD_DEV#*,}"
  open_mixers "$CARD" "$VOL_PCT"

  MODEL="$(choose_model)"; echo "[i] model active: $MODEL"
  if ! gen_tts_wav "$MODEL" "$TEXT" "$OUT"; then echo "[!] TTS generation failed"; echo "--- TTS STACKFLOW: DONE (LANG=${LANG_SEL}, STATUS=FAIL, MODEL=${MODEL}, FILE=${OUT}) ---"; exit 0; fi
  BYTES="$(wc -c < "$OUT" | tr -d ' ')"; echo "[i] generated: $OUT (bytes=${BYTES})"

  # apply gain first if requested
  PLAY="$OUT"
  if [ "$GAIN_VAL" != "1.0" ]; then
    if apply_gain "$OUT" "$OUT_GAIN" "$GAIN_VAL"; then PLAY="$OUT_GAIN"; echo "[i] gain applied: ${GAIN_MODE} -> $PLAY"; fi
  fi

  # pick device
  if [ -n "$ALSA_DEVICE" ]; then DEV_SPEC="$ALSA_DEVICE"; RATE=""; CH=""; else
    if [ -n "$CARD" ] && [ -n "$DEV" ]; then DEV_SPEC="plughw:${CARD},${DEV}"; else DEV_SPEC="default"; fi
  fi
  echo "[i] device: ${DEV_SPEC}"

  # try play
  if ! play_once "$DEV_SPEC" "$PLAY" "" ""; then
    if resample_to_48k_stereo "$PLAY" "$OUT_RES"; then
      FINAL="$OUT_RES"
      if [ "$GAIN_VAL" != "1.0" ]; then
        if apply_gain "$OUT_RES" "$OUT_RES_GAIN" "$GAIN_VAL"; then FINAL="$OUT_RES_GAIN"; fi
      fi
      if [ -n "$CARD" ] && [ -n "$DEV" ]; then
        DEV_SPEC="hw:${CARD},${DEV}"; RATE="48000"; CH="2"
        if ! play_once "$DEV_SPEC" "$FINAL" "$RATE" "$CH"; then
          echo "[!] playback failed after resample"; echo "--- TTS STACKFLOW: DONE (LANG=${LANG_SEL}, STATUS=FAIL, MODEL=${MODEL}, FILE=${FINAL}) ---"; exit 0
        fi
      else
        echo "[!] hw device not available for fallback"; echo "--- TTS STACKFLOW: DONE (LANG=${LANG_SEL}, STATUS=FAIL, MODEL=${MODEL}, FILE=${FINAL}) ---"; exit 0
      fi
    else
      echo "[!] resample failed"; echo "--- TTS STACKFLOW: DONE (LANG=${LANG_SEL}, STATUS=FAIL, MODEL=${MODEL}, FILE=${PLAY}) ---"; exit 0
    fi
  fi

  if [ "$LOOP_FLAG" = "1" ]; then
    echo "[i] LOOP mode on (Ctrl-C to stop)"
    while :; do
      if   [ -s "$OUT_RES_GAIN" ]; then play_once "$DEV_SPEC" "$OUT_RES_GAIN" "${RATE:-48000}" "${CH:-2}"
      elif [ -s "$OUT_RES"      ]; then play_once "$DEV_SPEC" "$OUT_RES"      "${RATE:-48000}" "${CH:-2}"
      elif [ -s "$OUT_GAIN"     ]; then play_once "$DEV_SPEC" "$OUT_GAIN"     "" ""
      else                             play_once "$DEV_SPEC" "$OUT"          "" ""
      fi
    done
  fi

  echo "[OK] playback: $DEV_SPEC${RATE:+ (fmt ${RATE}Hz ${CH}ch)}"
  echo "--- TTS STACKFLOW: DONE (LANG=${LANG_SEL}, STATUS=OK, MODEL=${MODEL}, FILE=${OUT_RES_GAIN:-${OUT_RES:-${OUT_GAIN:-$OUT}}}) ---"
  exit 0
}

main
EOS

REMOTE="/tmp/tts_stackflow_remote.sh"
chmod +x "${REMOTE_LOCAL}"

# --- push & run ---
"${ADB[@]}" push "${REMOTE_LOCAL}" "${REMOTE}" >/dev/null
rm -f "${REMOTE_LOCAL}"

# base64 for text
if command -v base64 >/dev/null 2>&1; then TEXT_B64="$(printf '%s' "$TEXT" | base64 | tr -d '\n')"; else TEXT_B64="$TEXT"; fi
PASS_ALSA="${ALSA_DEVICE:-__NONE__}"
GA_LIN="${GAIN_LIN:-__NONE__}"
GA_DB="${GAIN_DB:-__NONE__}"

"${ADB[@]}" shell sh "${REMOTE}" \
  "$(echo "${LANG_SEL}" | tr '[:lower:]' '[:upper:]')" \
  "${TEXT_B64}" \
  "${PASS_ALSA}" \
  "${VOL_PCT}" \
  "${LOOP_FLAG}" \
  "${GA_LIN}" \
  "${GA_DB}"

exit $?
