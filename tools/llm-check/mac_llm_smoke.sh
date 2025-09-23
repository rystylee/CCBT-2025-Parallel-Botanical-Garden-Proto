#!/usr/bin/env bash
# mac_llm_smoke.sh — push & run (PTY-friendly), CMake build with target autodetect, live output
# -----------------------------------------------------------------------------
# 特徴:
# - adb push → adb shell sh /tmp/... で実行（PTY必須端末でも確実に終了）
# - llama.cpp を CMake でビルド（EXAMPLES=ON, SERVER=OFF, TESTS=OFF, CURL=OFF, OPENMP=OFF）
# - ターゲット名の差異に自動対応（llama-cli → llama → main）
# - ビルド進捗を5秒おきに出力（/tmp/llm_build.log の末尾）
# - タイムアウト（環境変数 LLM_BUILD_TIMEOUT、秒）／0で無効
# - 生成は `tee` で “画面にも”流す（同時に /tmp/llm_smoke_<LANG>.txt に保存）
#
# 主要な環境変数（任意設定）
#   LLM_BUILD_TIMEOUT : ビルドのタイムアウト秒（既定 900、0で無制限）
#   N_TOKENS          : 生成トークン数（既定 32）
#   N_CTX             : コンテキスト長（既定 1024）
#   N_THREADS         : スレッド数（既定はCPUコア数）
#
# 使用例:
#   LLM_BUILD_TIMEOUT=0 N_TOKENS=32 N_CTX=1024 bash mac_llm_smoke.sh -l JP
# -----------------------------------------------------------------------------

set -euo pipefail

LANG_SEL=""
SERIAL="${ADB_SERIAL:-}"

# デフォルト値（環境変数で上書き可）
BUILD_TIMEOUT="${LLM_BUILD_TIMEOUT:-900}"
TOKENS_DEFAULT="${N_TOKENS:-32}"
CTX_DEFAULT="${N_CTX:-1024}"
THREADS_DEFAULT="${N_THREADS:-}"

print_help() {
  cat <<'EOF'
Usage: bash mac_llm_smoke.sh -l JP|EN|CN|FR [-s SERIAL]

Options:
  -l LANG    言語を指定（JP|EN|CN|FR）
  -s SERIAL  adb のデバイスシリアル（複数台接続時）。環境変数 ADB_SERIAL でも可
  -h         このヘルプ

Env:
  LLM_BUILD_TIMEOUT  ビルドのタイムアウト秒（既定 900、0で無制限）
  N_TOKENS           生成トークン数（既定 32）
  N_CTX              コンテキスト長（既定 1024）
  N_THREADS          スレッド数（既定はCPUコア数を自動検出）

出力:
  /tmp/llm_smoke_<LANG>.txt …… デバイス側に生成結果を保存（同時に画面にも表示）
  /tmp/llm_build.log           …… ビルド詳細ログ
  /tmp/llm_targets.txt         …… CMake ターゲット一覧
  終了行: --- LLM SMOKE: DONE (LANG=XX, STATUS=OK/FAIL, EXE=/path/to/bin) ---
EOF
}

# --- parse args ---
while [ $# -gt 0 ]; do
  case "$1" in
    -l) LANG_SEL="$2"; shift 2 ;;
    -s) SERIAL="$2"; shift 2 ;;
    -h|--help) print_help; exit 0 ;;
    *) echo "[!] Unknown option: $1" >&2; print_help; exit 1 ;;
  esac
done

if [ -z "${LANG_SEL}" ]; then
  echo "[!] -l JP|EN|CN|FR を指定してください" >&2
  exit 1
fi

# --- tools on Mac ---
if ! command -v adb >/dev/null 2>&1; then
  echo "[!] adb not found. Install with: brew install android-platform-tools" >&2
  exit 1
fi

# --- choose device ---
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
    printf "    devices:\n%s\n" "${devs}"
    return 1
  else
    printf "%s" "${devs}"
    return 0
  fi
}

SERIAL="$(choose_serial)" || exit 1
ADB=(adb -s "${SERIAL}")
echo "[i] Using device: ${SERIAL}"

# --- map language -> model/url/prompt ---
case "$(echo "${LANG_SEL}" | tr '[:lower:]' '[:upper:]')" in
  JP)
    MODEL_NAME="TinySwallow-1.5B-Instruct"
    MODEL_FILE="tinyswallow-1.5b-instruct-q5_k_m.gguf"
    MODEL_URL="https://huggingface.co/SakanaAI/TinySwallow-1.5B-Instruct-GGUF/resolve/main/tinyswallow-1.5b-instruct-q5_k_m.gguf?download=true"
    PROMPT="来場者に向けた日本語の挨拶文を3行で作成してください。丁寧で簡潔に。"
    ;;
  EN)
    MODEL_NAME="Llama-3.2-1B-Instruct"
    MODEL_FILE="Llama-3.2-1B-Instruct-Q4_K_M.gguf"
    MODEL_URL="https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf?download=true"
    PROMPT="Write a friendly two-sentence greeting for visitors. Keep it concise."
    ;;
  CN)
    MODEL_NAME="Qwen2.5-1.5B-Instruct"
    MODEL_FILE="qwen2.5-1.5b-instruct-q5_k_m.gguf"
    MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q5_k_m.gguf?download=true"
    PROMPT="请用两句话向来访者致意，语气友好而简洁。"
    ;;
  FR)
    MODEL_NAME="Llama-3.2-1B-Instruct"
    MODEL_FILE="Llama-3.2-1B-Instruct-Q4_K_M.gguf"
    MODEL_URL="https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf?download=true"
    PROMPT="Rédige une salutation conviviale en deux phrases pour des visiteurs. Reste concis."
    ;;
  *)
    echo "[!] Unsupported language: ${LANG_SEL} (use JP|EN|CN|FR)" >&2
    exit 1 ;;
esac

# --- create remote script and push ---
REMOTE_LOCAL="$(mktemp -t llm_smoke_remote.XXXXXX.sh)"
cat > "${REMOTE_LOCAL}" <<'EOS'
#!/bin/sh
# llm_smoke_remote.sh — runs on the device
set -eu

LANG_SEL="$1"
MODEL_NAME="$2"
MODEL_FILE="$3"
MODEL_URL="$4"
PROMPT="$5"
BUILD_TIMEOUT="${6:-900}"
TOKENS_DEFAULT="${7:-32}"
CTX_DEFAULT="${8:-1024}"
THREADS_DEFAULT="${9:-}"

BASE="/usr/local/llm"
BIN_DIR="$BASE/bin"
MOD_DIR="$BASE/models"
LLAMA_DIR="$BASE/llama.cpp"
BUILD_DIR="$LLAMA_DIR/build"
OUT="/tmp/llm_smoke_${LANG_SEL}.txt"
BUILD_LOG="/tmp/llm_build.log"
TARGETS_TXT="/tmp/llm_targets.txt"

export DEBIAN_FRONTEND=noninteractive

need() { command -v "$1" >/dev/null 2>&1; }
log(){ printf "%s\n" "$*"; }

ensure_deps() {
  if need apt-get; then
    need curl || (apt-get update >>"$BUILD_LOG" 2>&1 && apt-get install -y curl ca-certificates >>"$BUILD_LOG" 2>&1 || true)
    if ! need cmake || ! need g++ || ! need make || ! need git; then
      apt-get update >>"$BUILD_LOG" 2>&1
      apt-get install -y git build-essential cmake >>"$BUILD_LOG" 2>&1 || true
    fi
  fi
}

build_with_logs() {
  tgt="$1"
  echo "[build] start: $tgt" >>"$BUILD_LOG"
  ( cmake --build "$BUILD_DIR" -j1 --target "$tgt" >>"$BUILD_LOG" 2>&1 ) &
  BPID=$!
  elapsed=0
  while kill -0 "$BPID" 2>/dev/null; do
    LINES="$(tail -n 6 "$BUILD_LOG" 2>/dev/null || true)"
    if [ -n "$LINES" ]; then
      echo "$LINES" | sed 's/^/[build] /'
    fi
    sleep 5
    elapsed=$((elapsed+5))
    if [ "$BUILD_TIMEOUT" -gt 0 ] && [ "$elapsed" -ge "$BUILD_TIMEOUT" ]; then
      echo "[!] build timeout (${BUILD_TIMEOUT}s): $tgt" | tee -a "$BUILD_LOG" >/dev/null
      kill -9 "$BPID" 2>/dev/null || true
      wait "$BPID" 2>/dev/null || true
      return 1
    fi
  done
  wait "$BPID"
  return $?
}

ensure_llamacpp() {
  mkdir -p "$BIN_DIR" "$MOD_DIR"
  if [ -x "$BIN_DIR/llama-cli" ] || [ -x "$BIN_DIR/llama" ]; then
    return 0
  fi
  if [ ! -d "$LLAMA_DIR" ]; then
    if need git; then
      log "[i] cloning llama.cpp -> $LLAMA_DIR"
      # 公式は ggml-org/llama.cpp に移行
      git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR" >>"$BUILD_LOG" 2>&1 || true
    fi
  fi
  if [ -d "$LLAMA_DIR" ]; then
    log "[i] cmake configure -> $BUILD_DIR"
    mkdir -p "$BUILD_DIR"
    cmake -S "$LLAMA_DIR" -B "$BUILD_DIR" \
      -DCMAKE_BUILD_TYPE=Release \
      -DLLAMA_BUILD_EXAMPLES=ON \
      -DLLAMA_BUILD_SERVER=OFF \
      -DLLAMA_BUILD_TESTS=OFF \
      -DLLAMA_CURL=OFF \
      -DGGML_OPENMP=OFF >>"$BUILD_LOG" 2>&1 || true

    log "[i] cmake targets (help)"
    cmake --build "$BUILD_DIR" --target help >"$TARGETS_TXT" 2>&1 || true

    log "[i] cmake build (try llama-cli, then llama, then main)"
    for tgt in llama-cli llama main; do
      if grep -qi "$tgt" "$TARGETS_TXT"; then
        build_with_logs "$tgt" || true
      fi
    done

    # copy any plausible executable
    for exe in "$BUILD_DIR/bin/llama-cli" "$BUILD_DIR/bin/llama" "$BUILD_DIR/llama-cli" "$BUILD_DIR/llama"; do
      if [ -x "$exe" ]; then
        cp "$exe" "$BIN_DIR/" || true
      fi
    done
    if [ ! -x "$BIN_DIR/llama-cli" ] && [ ! -x "$BIN_DIR/llama" ]; then
      CAND="$(find "$BUILD_DIR" -type f -perm -111 -name 'llama*' 2>/dev/null | head -n 1 || true)"
      if [ -n "${CAND:-}" ]; then
        cp "$CAND" "$BIN_DIR/llama" || true
      fi
    fi
  fi
}

download_model() {
  mkdir -p "$MOD_DIR"
  dst="$MOD_DIR/$MODEL_FILE"
  if [ -s "$dst" ]; then
    log "[i] model exists: $dst"
    return 0
  fi
  if need curl; then
    log "[i] downloading: $MODEL_NAME -> $dst"
    curl -L --fail --retry 3 -o "$dst" "$MODEL_URL" >>"$BUILD_LOG" 2>&1 || {
      log "[!] download failed (see $BUILD_LOG)"
      return 1
    }
  else
    log "[!] curl not available; cannot download model"
    return 1
  fi
}

run_gen() {
  EXE=""
  if   [ -x "$BIN_DIR/llama-cli" ]; then EXE="$BIN_DIR/llama-cli"
  elif [ -x "$BIN_DIR/llama"     ]; then EXE="$BIN_DIR/llama"
  fi
  if [ -z "$EXE" ]; then
    log "[!] llama executable not found (see $BUILD_LOG)"
    return 2
  fi

  # 既定のスレッド数 = CPU コア数
  NPROC="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 2)"
  TOK="${N_TOKENS:-$TOKENS_DEFAULT}"
  CTX="${N_CTX:-$CTX_DEFAULT}"
  TH="${N_THREADS:-${THREADS_DEFAULT:-$NPROC}}"

  # llama-cli が --timings をサポートしているか検出
  TIMINGS_OPT=""
  if "$EXE" -h 2>&1 | grep -q -- '--timings'; then
    TIMINGS_OPT="--timings"
  fi

  log "[i] exe: $EXE"
  log "[i] model: $MOD_DIR/$MODEL_FILE"
  log "[i] prompt: $PROMPT"
  log "[i] gen: -n $TOK -c $CTX -t $TH ${TIMINGS_OPT}"

  # パイプの先頭コマンド（llama-cli）の終了コードを確実に取得
  ECFILE="/tmp/llm_exit_${LANG_SEL}.$$"
  if command -v stdbuf >/dev/null 2>&1; then
    ( stdbuf -oL -eL "$EXE" -m "$MOD_DIR/$MODEL_FILE" -p "$PROMPT" \
        -n "$TOK" -t "$TH" -c "$CTX" --temp 0.7 --top-p 0.95 ${TIMINGS_OPT} 2>&1 ; \
      echo $? > "$ECFILE" ) | tee "$OUT"
  else
    ( "$EXE" -m "$MOD_DIR/$MODEL_FILE" -p "$PROMPT" \
        -n "$TOK" -t "$TH" -c "$CTX" --temp 0.7 --top-p 0.95 ${TIMINGS_OPT} 2>&1 ; \
      echo $? > "$ECFILE" ) | tee "$OUT"
  fi
  EC="$(cat "$ECFILE" 2>/dev/null || echo 1)"; rm -f "$ECFILE"

  if [ "$EC" -ne 0 ]; then
    log "[!] generation failed (exit=$EC)"
    return 3
  fi

  log "[OK] saved: $OUT"
  return 0
}

ensure_deps
ensure_llamacpp
download_model || true
STATUS="FAIL"; EXE_PATH="N/A"
if run_gen; then
  STATUS="OK"
  if   [ -x "$BIN_DIR/llama-cli" ]; then EXE_PATH="$BIN_DIR/llama-cli"
  elif [ -x "$BIN_DIR/llama"     ]; then EXE_PATH="$BIN_DIR/llama"
  fi
fi
echo "--- LLM SMOKE: DONE (LANG=${LANG_SEL}, STATUS=${STATUS}, EXE=${EXE_PATH}) ---"
exit 0
EOS

REMOTE="/tmp/llm_smoke_remote.sh"
chmod +x "${REMOTE_LOCAL}"
"${ADB[@]}" push "${REMOTE_LOCAL}" "${REMOTE}" >/dev/null
rm -f "${REMOTE_LOCAL}"

# --- run remote script and exit cleanly ---
# shellcheck disable=SC2086
"${ADB[@]}" shell sh "${REMOTE}" \
  "$(echo "${LANG_SEL}" | tr '[:lower:]' '[:upper:]')" \
  "${MODEL_NAME}" "${MODEL_FILE}" "${MODEL_URL}" "${PROMPT}" \
  "${BUILD_TIMEOUT}" "${TOKENS_DEFAULT}" "${CTX_DEFAULT}" "${THREADS_DEFAULT}"

# done
exit $?
