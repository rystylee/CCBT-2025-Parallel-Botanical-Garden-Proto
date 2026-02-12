\
#!/usr/bin/env bash
# mac_tts_chunker.sh — split long text into segments and call mac_tts_stackflow_smoke.sh per segment
# Safe for JP (and other langs), respects punctuation boundaries. Optional loop.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SMOKE="$SCRIPT_DIR/mac_tts_stackflow_smoke.sh"

LANG="JP"
SERIAL="${ADB_SERIAL:-}"
TEXT_INPUT=""
TEXT_FILE=""
VOL_PCT=""
GAIN_LIN=""
GAIN_DB=""
LOOP_FLAG=0
ALSA_DEVICE="${ALSA_DEVICE:-}"
CHARS_PER_SEG="${CHARS_PER_SEG:-160}"   # default segment length
BREAK_MS="${BREAK_MS:-200}"              # pause between segments

print_help() {
  cat <<'EOF'
Usage: bash mac_tts_chunker.sh [-l JP|EN|CN|FR] [-t "text" | -f file.txt] [options]

Options:
  -l LANG          言語（既定 JP）
  -t "TEXT"        読み上げテキスト
  -f FILE          テキストファイルから読み込み（-t より優先）
  -L               全セグメントをループ再生（Ctrl-Cで停止）
  -V 0-100         ミキサ音量（ベストエフォート）
  -g 0.0-1.0       WAV 線形ゲイン
  -d dB            WAV dB 指定（例: -12）
  -s SERIAL        adb デバイス指定
Env:
  ALSA_DEVICE      再生デバイス（例: hw:0,1 / plughw:0,1）
  CHARS_PER_SEG    セグメント長の上限（既定 160）
  BREAK_MS         セグメント間の無音休止（既定 200ms）
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -l) LANG="$2"; shift 2 ;;
    -t) TEXT_INPUT="$2"; shift 2 ;;
    -f) TEXT_FILE="$2"; shift 2 ;;
    -L) LOOP_FLAG=1; shift 1 ;;
    -V) VOL_PCT="$2"; shift 2 ;;
    -g) GAIN_LIN="$2"; shift 2 ;;
    -d) GAIN_DB="$2";  shift 2 ;;
    -s) SERIAL="$2"; shift 2 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "[!] Unknown option: $1" >&2; print_help; exit 1 ;;
  esac
done

if [ -n "$TEXT_FILE" ]; then
  [ -f "$TEXT_FILE" ] || { echo "[!] file not found: $TEXT_FILE" >&2; exit 1; }
  TEXT="$(cat "$TEXT_FILE")"
else
  TEXT="$TEXT_INPUT"
fi
[ -n "$TEXT" ] || { echo "[!] Provide text via -t or -f" >&2; exit 1; }

# Split TEXT into segments ~CHARS_PER_SEG respecting punctuation
SEG_FILE="$(mktemp -t tts_segments.XXXXXX.txt)"
python3 - "$TEXT" "$CHARS_PER_SEG" >"$SEG_FILE" <<'PY'
import sys, textwrap, re
txt = sys.argv[1]
try:
    limit = int(sys.argv[2])
except Exception:
    limit = 160
# Normalize newlines
txt = re.sub(r'\r\n?', '\n', txt).strip()
# Prefer to split on JP punctuation / sentence enders
seps = '。．！？!?；;：:\n'
buf = ''
out = []
for ch in txt:
    buf += ch
    if len(buf) >= limit or ch in seps:
        out.append(buf.strip())
        buf = ''
if buf.strip():
    out.append(buf.strip())
# Fallback: ensure no segment exceeds limit by greedy split
final = []
for seg in out:
    if len(seg) <= limit:
        final.append(seg)
        continue
    start = 0
    while start < len(seg):
        final.append(seg[start:start+limit])
        start += limit
for s in final:
    print(s)
PY

count="$(wc -l < "$SEG_FILE" | tr -d ' ')"
echo "[i] segments: $count (limit=${CHARS_PER_SEG} chars)"

run_one() {
  local seg="$1"
  local args=(-l "$LANG" -t "$seg")
  [ -n "$VOL_PCT" ]  && args+=(-V "$VOL_PCT")
  [ -n "$GAIN_LIN" ] && args+=(-g "$GAIN_LIN")
  [ -n "$GAIN_DB" ]  && args+=(-d "$GAIN_DB")
  [ -n "$SERIAL" ]   && args+=(-s "$SERIAL")
  ALSA_DEVICE="$ALSA_DEVICE" "$SMOKE" "${args[@]}"
}

if [ "$LOOP_FLAG" -eq 1 ]; then
  echo "[i] LOOP mode (Ctrl-C to stop)"
  while :; do
    i=0
    while IFS= read -r line || [ -n "$line" ]; do
      i=$((i+1))
      echo "[seg $i/$count]"
      run_one "$line"
      python3 - "$BREAK_MS" - <<'PY' >/dev/null 2>&1 || true
import sys, time
try:
  ms = int(sys.argv[1])
except: ms = 200
time.sleep(max(ms,0)/1000.0)
PY
    done < "$SEG_FILE"
  done
else
  i=0
  while IFS= read -r line || [ -n "$line" ]; do
    i=$((i+1))
    echo "[seg $i/$count]"
    run_one "$line"
    python3 - "$BREAK_MS" - <<'PY' >/dev/null 2>&1 || true
import sys, time
try:
  ms = int(sys.argv[1])
except: ms = 200
time.sleep(max(ms,0)/1000.0)
PY
  done < "$SEG_FILE"
fi

rm -f "$SEG_FILE"
exit 0
