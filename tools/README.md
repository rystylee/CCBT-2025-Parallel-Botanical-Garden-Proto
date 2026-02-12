# m5_update_ax630c.sh — M5Stack LLM (AX630C) セットアップ手順

このリポジトリ外部の端末（Mac）から、USB Type‑C 経由の **ADB** で M5Stack LLM Module（AX630C）に対して、
- StackFlow APT レポの追加
- 基本ツールの導入（git/curl/unzip/tmux）
- `uv` の導入
- **プライベート GitHub リポ**（main ブランチ）のクローン（PAT を URL に埋め込み）
- `scripts/download_tinyswallow.sh` の実行
- melotts モデル類のインストール

を自動実行するための **プロビジョニング・スクリプト** `m5_update_ax630c.sh` の使い方まとめです。

> **対象機材**: M5Stack Module LLM / LLM630 Compute Kit (AX630C)
>
> **前提 OS**: Ubuntu 22.04 (Jammy) 系（デバイス側）

---

## 0. 事前準備（Mac 側 / m5stack wifi接続）

1) **ADB の用意**

```bash
# 未導入なら
brew install android-platform-tools
```

2) **デバイスの USB デバッグ許可**  
USB‑C で接続後、以下で認識を確認：

```bash
adb devices
```

`unauthorized` と表示された場合は、デバイス側の許可ダイアログで許可してください。

3) **M5STACKのネットワーク接続**  
下記記事を参照
https://dev.classmethod.jp/articles/m5stack-llm630-compute-kit-wifi-setup/

---

## 1. GitHub パーソナルアクセストークン（PAT）の設定（Mac）

プライベートリポをクローンするため、**PAT** を環境変数 `GITHUB_TOKEN` へ設定します。履歴に残さない方法：

```bash
# 非表示入力で設定
read -s GITHUB_TOKEN && export GITHUB_TOKEN
# もしくは（履歴に残るので注意）
# export GITHUB_TOKEN='ghp_XXXXXXXXXXXXXXXXXXXXXXXXXXXX'
```

> 必要権限: `repo` スコープ（組織SSOの場合は Authorize を忘れずに）

---

## 2. スクリプトをデバイスへ転送して実行

1) **スクリプトファイルを転送**（ここではカレントに `m5_update_ax630c.sh` がある想定）

```bash
adb push m5_update_ax630c.sh /tmp/m5_update_ax630c.sh
```

2) **実行**（`GITHUB_TOKEN` を環境変数で渡す。bash で実行するのが安全）

```bash
adb shell env GITHUB_TOKEN="$GITHUB_TOKEN" bash /tmp/m5_update_ax630c.sh
```

> `/tmp` が `noexec` な環境では以下のように退避してから実行：  
> ```bash
> adb shell 'mkdir -p /data/local/tmp && cp /tmp/m5_update_ax630c.sh /data/local/tmp/ && chmod 755 /data/local/tmp/m5_update_ax630c.sh'
> adb shell env GITHUB_TOKEN="$GITHUB_TOKEN" bash /data/local/tmp/m5_update_ax630c.sh
> ```

---

## 3. 何が行われるか（内部処理の概要）

- StackFlow APT レポ鍵の取得・レポ追加  
- `apt-get update` → `git curl unzip tmux` の導入  
- `uv` の導入（ユーザ領域）  
- `https://github.com/rystylee/CCBT-2025-Parallel-Botanical-Garden-Proto` の **main** を、PAT 埋め込みで **`/opt/ccbt-2025-pbg`** へ clone  
  - clone 直後に `origin` の URL から PAT を **除去**（漏洩防止）  
- LLM モデル（`llama3.2-1b-prefill-ax630c` / `qwen2.5-1.5b-ax630c`）のインストール  
- `scripts/download_tinyswallow.sh` を実行  
- melotts モデル（`en-us` / `ja-jp` / `zh-cn`）のインストール  
- 終了時に `✅ Provision finished on <hostname>` を表示

---

## 4. 成功確認

```bash
# デバイス側に入って確認（例）
adb shell

# APT レポ
grep -R "repo.llm.m5stack.com" /etc/apt/sources.list.d/

# リポが落ちているか
ls -la /opt/ccbt-2025-pbg

# モデル（例）
apt-cache policy llm-model-llama3.2-1b-prefill-ax630c
apt-cache policy llm-model-qwen2.5-1.5b-ax630c
apt-cache policy llm-model-melotts-ja-jp
```

---

## 5. 各種動作チェック

```bash
# audio
bash audio-check/mac_audio_check.sh

# llm
LLM_BUILD_TIMEOUT=0 bash tools/llm-check/mac_llm_smoke.sh -l JP

# tts
bash tools/tts-check/mac_tts_stackflow_smoke.sh -l JP -L -g 0.2
bash tools/tts-check/mac_tts_stackflow_smoke.sh -l JP -t 'ご来場ありがとうございます。本展示 をゆっくりお楽しみください。' -d -15


```

---

## 6. トラブルシュート

### 「DEBIAN_FRONTEND=noninteractive: command not found」
`sudo` の前に環境変数を置くと **コマンドと誤認**されます。本スクリプトは `apt_i()` 関数で吸収済み。古い版を使っている場合は最新版を利用してください。

### `sudo: not found` / 権限エラー
デバイスに `sudo` がない場合や root 権限が必須な環境では、**root シェル**で実行してください：
```bash
adb shell su -c 'env GITHUB_TOKEN="$GITHUB_TOKEN" bash /tmp/m5_update_ax630c.sh'
```

### `/tmp` が noexec
上の **2. 実行** の欄にある「退避して実行」の例を参照してください。

### ネットワーク制限（GitHub / M5 APT へ出られない）
Mac でリポを clone → `tar czf repo.tgz` → `adb push repo.tgz` → デバイスで解凍 → `scripts/...` 実行でも代替可能です。

### トークン露出の抑制
- PAT は**ファイルに書かず**、**環境変数**で渡します。
- clone 直後に `origin` の URL から PAT を削除します。
- 実行後にデバイスを再起動すると環境がクリアされます。

---

## 7. 片付け（任意）

```bash
# スクリプト削除
adb shell rm -f /tmp/m5_update_ax630c.sh
# または退避先に置いた場合
adb shell rm -f /data/local/tmp/m5_update_ax630c.sh
```

---

## 8. ライセンス / 免責

本スクリプトは社内・個人開発向けの補助用途です。実行により発生した損害について作者は責を負いません。運用環境に合わせて改変してご利用ください。
