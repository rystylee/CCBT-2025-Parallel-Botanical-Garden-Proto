#!/usr/bin/env bash
# Provision script for M5 LLM (AX630C) via ADB
# - Adds M5Stack StackFlow APT repo
# - Installs base tools, uv
# - Clones private repo (main) with token from env
# - Runs scripts/download_tinyswallow.sh
# - Installs melotts models
set -euo pipefail

# ====== 設定 ======
REPO_SLUG='rystylee/CCBT-2025-Parallel-Botanical-Garden-Proto'
BRANCH='main'
TARGET_DIR='/opt/ccbt-2025-pbg'

# ====== 権限（root/非root 両対応） ======
_HAVE_SUDO=0
if command -v sudo >/dev/null 2>&1; then _HAVE_SUDO=1; fi
is_root() { [ "$(id -u)" -eq 0 ]; }

# 環境変数付きで apt を叩くユーティリティ（sudo 有無を吸収）
apt_i() {
  if is_root; then
    DEBIAN_FRONTEND=noninteractive apt-get "$@"
  else
    if [ "$_HAVE_SUDO" -eq 1 ]; then
      sudo -E DEBIAN_FRONTEND=noninteractive apt-get "$@"
    else
      echo "ERROR: root 権限が必要です（sudo なし）。root シェルで実行してください。" >&2
      exit 1
    fi
  fi
}

# root で書き込みが必要なときの tee ラッパ
as_root_tee() {
  if is_root; then
    tee "$@"
  else
    if [ "$_HAVE_SUDO" -eq 1 ]; then
      sudo tee "$@"
    else
      echo "ERROR: root 権限が必要です（sudo なし）。root シェルで実行してください。" >&2
      exit 1
    fi
  fi
}

# root でファイル作成/変更が必要な時の実行
as_root_sh() {
  if is_root; then
    sh -c "$*"
  else
    if [ "$_HAVE_SUDO" -eq 1 ]; then
      sudo sh -c "$*"
    else
      echo "ERROR: root 権限が必要です（sudo なし）。root シェルで実行してください。" >&2
      exit 1
    fi
  fi
}

# ====== APT レポ追加（StackFlow） ======
# keyrings ディレクトリ作成
as_root_sh 'install -d -m 0755 /etc/apt/keyrings'

# 鍵取得（wget 優先。無ければ最小限インストールして取得）
if command -v wget >/dev/null 2>&1; then
  as_root_sh 'wget -qO /etc/apt/keyrings/StackFlow.gpg https://repo.llm.m5stack.com/m5stack-apt-repo/key/StackFlow.gpg'
elif command -v curl >/dev/null 2>&1; then
  as_root_sh 'curl -fsSL https://repo.llm.m5stack.com/m5stack-apt-repo/key/StackFlow.gpg >/etc/apt/keyrings/StackFlow.gpg'
else
  apt_i update
  apt_i install -y wget ca-certificates
  as_root_sh 'wget -qO /etc/apt/keyrings/StackFlow.gpg https://repo.llm.m5stack.com/m5stack-apt-repo/key/StackFlow.gpg'
fi

echo 'deb [arch=arm64 signed-by=/etc/apt/keyrings/StackFlow.gpg] https://repo.llm.m5stack.com/m5stack-apt-repo jammy ax630c' \
| as_root_tee /etc/apt/sources.list.d/StackFlow.list >/dev/null

apt_i update

# ====== 基本ツール ======
apt_i install -y git curl unzip tmux

# ====== uv（指定あり） ======
# uv はユーザ領域に入る（root でも問題はないが標準はユーザ）
curl -LsSf https://astral.sh/uv/install.sh | sh

# ====== 私設リポ clone（トークンは env GITHUB_TOKEN から受け取る） ======
if [ -z "${GITHUB_TOKEN:-}" ]; then
  echo "ERROR: GITHUB_TOKEN が未設定です。実行時に env で渡してください。" >&2
  exit 1
fi

# 作業ディレクトリの用意
as_root_sh "rm -rf '$TARGET_DIR'"
as_root_sh "mkdir -p '$TARGET_DIR'"
# 所有権は現在の実行ユーザに
if is_root; then
  # root 実行時は root のままでOK（必要ならここで chown を変える）
  :
else
  as_root_sh "chown $(id -u):$(id -g) '$TARGET_DIR'"
fi

# clone（PAT を URL に埋め込む。特殊記号を含む PAT に備えて2パターン試行）
set +e
git clone -b "$BRANCH" "https://${GITHUB_TOKEN}@github.com/${REPO_SLUG}.git" "$TARGET_DIR"
CLONE_RC=$?
if [ $CLONE_RC -ne 0 ]; then
  git clone -b "$BRANCH" "https://${GITHUB_TOKEN}:x-oauth-basic@github.com/${REPO_SLUG}.git" "$TARGET_DIR"
  CLONE_RC=$?
fi
set -e
if [ $CLONE_RC -ne 0 ]; then
  echo "ERROR: リポジトリの clone に失敗しました。" >&2
  exit $CLONE_RC
fi

# origin からトークンを外す（漏えい防止）
git -C "$TARGET_DIR" remote set-url origin "https://github.com/${REPO_SLUG}.git"

# ====== モデル（指定の順序） ======
apt_i install -y \
  llm-model-llama3.2-1b-prefill-ax630c \
  llm-model-qwen2.5-1.5b-ax630c

# ====== スクリプト実行（リポ内） ======
if [ ! -x "$TARGET_DIR/scripts/download_tinyswallow.sh" ]; then
  # 実行ビットが無い場合も考慮
  chmod +x "$TARGET_DIR/scripts/download_tinyswallow.sh" 2>/dev/null || true
fi
bash "$TARGET_DIR/scripts/download_tinyswallow.sh"

# ====== melotts ======
apt_i install -y \
  llm-model-melotts-en-us \
  llm-model-melotts-ja-jp \
  llm-model-melotts-zh-cn

echo "✅ Provision finished on $(hostname)"
