# Monitor - Web管理UI

MonitorはFlask + SocketIOベースのWeb管理UIで、100台のBIデバイスを一元管理します。SSH経由でリモート操作、ログ監視、設定変更などを行うことができます。

---

## 概要

### 主な機能

- **8ページ構成の管理UI**: SYSTEM、LED、Sound、LLM、TTS、Run Scripts、Terminal、Broadcast
- **リアルタイム監視**: SocketIO経由でステータスとログをリアルタイム表示
- **SSH経由のリモート操作**: パスワード認証でBIデバイスに接続
- **マルチデバイス並行処理**: 最大20台の同時SSH接続
- **インタラクティブターミナル**: WebベースのSSHターミナル
- **コマンドブロードキャスト**: 全デバイスまたは選択デバイスへの一斉コマンド実行

### システム構成

```
[ブラウザ]
    ↓ HTTP/WebSocket
[Flask + SocketIO Server]
    ↓ SSH (paramiko)
[100台のBIデバイス: 10.0.0.1-100]
```

---

## ページ構成

### Page 1: SYSTEM (`/`)

システム全体の管理ページ：

- **Ping**: デバイスの疎通確認
- **Inet**: ネットワーク設定確認（`/etc/network/interfaces`）
- **Git Pull**: 最新コードを取得（`git stash && git pull`）
- **Reboot**: デバイス再起動

### Page 2: LED (`/led`)

LED制御ページ：

- **LED Server Start**: PCA9685 LED ServerをTmux起動（セッション: `bi_led_srv`）
- **LED Server Stop**: PCA9685 LED Serverを停止
- **LED Test**: LEDフェードテスト（0.0 → 1.0 → 0.0）
- **LED On/Off**: LED即座オン/オフ

### Page 3: Sound (`/sound`)

音声テストページ：

- **Test Sound**: テスト音声再生（`aplay -D dmixer /usr/local/m5stack/audio_check.wav`）

### Page 4: LLM (`/llm`)

LLMテストページ：

- **LLM Check**: LLM推論テスト（`scripts/check_llm.py`）
- **Tmuxセッション**: `bi_llm`

### Page 5: TTS (`/tts`)

TTSテストページ：

- **TTS Check**: TTS音声生成テスト（`scripts/check_tts.py`）
- **Tmuxセッション**: `bi_tts`

### Page 6: Run Scripts (`/run`)

BIシステム起動・停止ページ：

- **Start**: `main.py`をTmux起動（セッション: `bi_main`）
- **Stop**: `main.py`を停止
- **Restart**: 停止→起動
- **Logs**: リアルタイムログ表示（`/tmp/bi_run.log`）

### Page 7: Terminal (`/terminal`)

インタラクティブSSHターミナル：

- **WebベースのSSHターミナル**: デバイスにSSH接続してコマンド実行
- **複数デバイス切替**: デバイスIDを指定して接続先を変更

### Page 8: Broadcast (`/broadcast`)

コマンドブロードキャスト：

- **全デバイスへコマンド送信**: 1-100台の全デバイスに一斉コマンド実行
- **選択デバイスへ送信**: 特定のデバイスのみを選択して実行
- **並行実行**: 最大20台の同時SSH接続

---

## インストール

### 前提条件

- Ubuntu PC またはMac（10.0.0.200など）
- Python 3.10以上
- BIデバイスへのSSHアクセス（ユーザー: root、パスワード認証）

### 依存関係

```bash
# Pythonパッケージをインストール
cd monitor
pip install flask flask-socketio paramiko python-osc
```

---

## 設定

### monitor/app.py の設定項目

```python
NODE_PREFIX = "10.0.0"       # デバイスIPの接頭辞
NODE_COUNT  = 100            # デバイス数
OSC_PORT    = 9000           # LEDサーバーのOSCポート
SSH_USER    = "root"         # SSHユーザー名
GIT_DIR     = "/root/dev/CCBT-2025-Parallel-Botanical-Garden-Proto"  # Gitリポジトリパス
SOUND_CMD   = "aplay -D dmixer /usr/local/m5stack/audio_check.wav"   # テスト音声コマンド
SSH_PASS    = getpass.getpass("SSH Password: ")  # SSH パスワード（起動時に入力）
```

---

## 起動方法

### Monitorサーバーの起動

```bash
cd monitor
python app.py
```

起動時にSSHパスワードの入力を求められます：

```
SSH Password: ********
 * Running on http://0.0.0.0:5000
```

### ブラウザでアクセス

```
http://10.0.0.200:5000
```

または

```
http://localhost:5000
```

---

## 使用方法

### デバイス選択

各ページで、1-100のデバイスIDを選択してコマンドを実行：

```
Device IDs: [1] [2] [3] ... [100]
```

### コマンド実行

1. デバイスIDをクリックして選択
2. アクションボタンをクリック（例: "Ping"、"Git Pull"、"Start"など）
3. ステータスが表示される（"running" → "success" / "error"）

### ログ表示

Run ScriptsページでLogsボタンをクリックすると、リアルタイムログが表示されます：

```
[2024-01-01 12:00:00] INFO: Initialize App Controller...
[2024-01-01 12:00:01] INFO: BI Controller initialized
[2024-01-01 12:00:02] INFO: Starting OSC server
...
```

### インタラクティブターミナル

Terminalページで：

1. デバイスIDを入力
2. "Connect"ボタンをクリック
3. WebベースのSSHターミナルが開く
4. コマンドを入力して実行

```bash
# 例
root@m5stack-1:~# ls
root@m5stack-1:~# cd /root/dev/CCBT-2025-Parallel-Botanical-Garden-Proto
root@m5stack-1:~/dev/CCBT-2025-Parallel-Botanical-Garden-Proto# git status
```

### コマンドブロードキャスト

Broadcastページで：

1. コマンドを入力（例: `uname -a`）
2. "All Devices"または特定のデバイスIDを選択
3. "Execute"ボタンをクリック
4. 並行実行されて結果が表示される

---

## Tmuxセッション管理

### セッション一覧

- `bi_main`: BIシステム（main.py）
- `bi_llm`: LLMテスト（scripts/check_llm.py）
- `bi_tts`: TTSテスト（scripts/check_tts.py）
- `bi_led_srv`: LED Server（pca9685_osc_led_server.py）

### Tmuxコマンド

MonitorはSSH経由で以下のTmuxコマンドを実行：

```bash
# セッション開始
tmux new -d -s bi_main 'cd /root/dev/... && uv run python main.py 2>&1 | tee -a /tmp/bi_run.log'

# セッション停止
tmux kill-session -t bi_main

# セッション確認
tmux has-session -t bi_main 2>/dev/null && echo "running" || echo "stopped"
```

---

## リアルタイムログ

### ログファイル

各BIデバイス上でログを記録：

```
/tmp/bi_run.log  # main.py のログ
```

### ログ取得

MonitorはSSH経由でログファイルを定期的に取得：

```bash
# 最新100行を取得
tail -n 100 /tmp/bi_run.log
```

### ログフォーマット

```
[2024-01-01 12:00:00] INFO: Initialize App Controller...
[2024-01-01 12:00:01] INFO: BI Controller initialized
[2024-01-01 12:00:02] INFO: Auto-starting BI cycle
[2024-01-01 12:00:03] INFO: Starting BI cycle
[2024-01-01 12:00:04] INFO: Starting OSC server
[2024-01-01 12:00:05] INFO: OSC Server started on 0.0.0.0:8000
[2024-01-01 12:00:06] INFO: RECEIVING phase started
```

---

## トラブルシューティング

### SSHパスワード認証に失敗する

```bash
# BIデバイス側でSSHサーバーが起動しているか確認
ssh root@10.0.0.1

# パスワードを確認
# app.py 起動時に正しいパスワードを入力
```

### デバイスが応答しない

```bash
# デバイスの疎通確認
ping 10.0.0.1

# SSHポートが開いているか確認
nc -zv 10.0.0.1 22
```

### Tmuxセッションが起動しない

```bash
# BIデバイスにSSH接続
ssh root@10.0.0.1

# Tmuxセッションを手動確認
tmux ls

# セッションを手動起動
tmux new -s bi_main
cd /root/dev/CCBT-2025-Parallel-Botanical-Garden-Proto
uv run python main.py
```

### ログが表示されない

```bash
# ログファイルの存在を確認
ssh root@10.0.0.1 "ls -la /tmp/bi_run.log"

# ログファイルの内容を確認
ssh root@10.0.0.1 "tail /tmp/bi_run.log"
```

---

## セキュリティ

### SSH パスワード

- **パスワードは起動時に入力**: `getpass.getpass("SSH Password: ")`
- **メモリ上のみに保持**: ファイルに保存されない
- **注意**: パスワードはメモリ上に平文で保持されるため、本番環境では公開鍵認証を推奨

### SSH接続制限

- **並行接続数制限**: セマフォで最大20接続
- **タイムアウト**: 10秒で接続タイムアウト

---

## 開発者向け情報

### Flask + SocketIO構成

```python
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

@app.route("/")
def index():
    return render_template("system.html")

@socketio.on("ping_device")
def handle_ping(data):
    device_id = data["device_id"]
    # SSH経由でpingコマンドを実行
    emit("ping_result", {"device_id": device_id, "status": "success"})
```

### SSH実行パターン

```python
def ssh_exec(device_id, command):
    ip = f"10.0.0.{device_id}"
    with SSH_SEMAPHORE:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username=SSH_USER, password=SSH_PASS, timeout=10)
        stdin, stdout, stderr = client.exec_command(command)
        result = stdout.read().decode()
        client.close()
    return result
```

### ログスクレイパー

```python
# ANSIエスケープシーケンスを除去
import re
ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mGKHF]|\x1b\(B|\x1b=|\x1b>')

def clean_log(text):
    return ANSI_RE.sub('', text)
```

---

## 関連ドキュメント

- **メインシステム**: [docs/requirements.md](requirements.md)
- **systemd自動起動**: [systemd/](../systemd/)
- **デプロイ手順**: [docs/deployment.md](deployment.md)（作成予定）
