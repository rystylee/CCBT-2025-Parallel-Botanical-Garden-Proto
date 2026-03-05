# PBG Monitor

Parallel Botanical Garden の全デバイス（100台・10クラスタ）を Web ブラウザから管理するためのモニターアプリケーションです。

---

## 機能一覧

### 1. Devices タブ — トポロジー俯瞰

100台のデバイスをクラスタ単位でグリッド表示します。各ノードの ID・IP・ゲートウェイ情報が一目で確認でき、ノードをクリックすると Terminal タブに遷移して即座に SSH 接続を開始できます。

### 2. Terminal タブ — 対話型 SSH

ブラウザ内で xterm.js ベースのフルターミナルが動作します。選択したデバイスに SSH 接続し、通常のターミナルと同じ操作が可能です。

- パッケージのインストール (`pip install ...`)
- ログの確認 (`journalctl`, `tail -f` 等)
- プロセス管理 (`systemctl`, `ps`, `kill`)
- ファイル編集 (`vim`, `nano`)
- Git 操作

### 3. Broadcast タブ — コマンド一斉送信

Terminal でデバッグ・検証したコマンドを、他のノードやクラスタ・全体に一括送信します。

**スコープ選択:**

| スコープ | 説明 | 例 |
|---------|------|----|
| All | 全100台に並列実行 | `uname -a` |
| Cluster | 指定クラスタの10台 | Cluster 3 を選択 |
| Node | 個別指定（範囲記法可） | `1,2,3` または `1-10` または `1-5,8,20-25` |

**結果表示:**
- リアルタイムにストリーミングで返ってくる
- 成功（緑）/ 失敗（赤）がステータスドットで判別可能
- クリックで stdout / stderr を展開
- 実行時間・exit code を表示

**Snippets:**
よく使うコマンドを名前を付けて保存・再利用できます。デフォルトで以下が登録済みです:

- System info (`uname -a && uptime`)
- Disk usage (`df -h /`)
- Service status (`systemctl status pbg --no-pager -l`)
- Last 50 logs (`journalctl -u pbg -n 50 --no-pager`)
- Python packages (`pip list`)
- Network check (`ip addr show`)
- Git status
- Restart service (`sudo systemctl restart pbg`)

---

## セットアップ

### 依存パッケージのインストール

```bash
pip install flask flask-socketio paramiko
```

### SSH 鍵の準備（推奨）

パスワード認証でも動作しますが、100台への Broadcast を行う場合は鍵認証を推奨します。

```bash
# モニター実行マシンで鍵を生成（未作成の場合）
ssh-keygen -t ed25519 -f ~/.ssh/pbg_monitor

# 全デバイスに公開鍵を配布
for i in $(seq 1 100); do
  ssh-copy-id -i ~/.ssh/pbg_monitor.pub m5stack@10.0.0.$i
done
```

---

## 起動方法

### 基本（パスワード認証）

```bash
python -m monitor.app \
  --csv config/networks.csv \
  --ssh-user m5stack \
  --ssh-password 'your-password'
```

### 鍵認証

```bash
python -m monitor.app \
  --csv config/networks.csv \
  --ssh-user m5stack \
  --ssh-key ~/.ssh/pbg_monitor
```

### 全オプション

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--csv` | `config/networks.csv` | ネットワーク定義 CSV のパス |
| `--host` | `0.0.0.0` | バインドアドレス |
| `--port` | `5000` | HTTP ポート番号 |
| `--ssh-user` | `m5stack` | SSH ユーザー名 |
| `--ssh-password` | なし | SSH パスワード |
| `--ssh-key` | なし | SSH 秘密鍵のパス |
| `--debug` | `false` | Flask デバッグモード |

起動後、ブラウザで `http://localhost:5000` にアクセスしてください。

---

## 使い方の典型的なフロー

### ① 特定デバイスのデバッグ

1. **Devices** タブで対象ノードをクリック
2. **Terminal** タブに遷移 → **Connect** で SSH 接続
3. ターミナル上で自由に操作（ログ確認、設定変更、パッケージ追加など）
4. 問題を特定・解決したら **Disconnect**

### ② デバッグ結果を全体に展開

1. Terminal で検証済みのコマンドをコピー
2. **Broadcast** タブに移動
3. コマンドをテキストエリアに貼り付け
4. スコープを選択（例: まず同じクラスタでテスト → 問題なければ All）
5. **Execute** で一斉実行
6. 結果をリアルタイムで確認
7. 必要に応じて **Save** でスニペットとして保存

### ③ 定期メンテナンス

1. **Broadcast** タブで Snippets から定型コマンドを選択
2. スコープを All に設定
3. 実行して全台の状態を一括確認

---

## ファイル構成

```
monitor/
├── __init__.py          # パッケージ初期化
├── app.py               # Flask + SocketIO メインアプリケーション
│                          - HTTP ルート (/api/devices)
│                          - WebSocket ハンドラ (SSH / Broadcast)
│                          - CLI エントリーポイント
├── ssh_manager.py       # SSH 接続管理
│                          - 対話型シェルセッション (paramiko)
│                          - コマンド単発実行
│                          - 並列ブロードキャスト
├── templates/
│   └── index.html       # SPA (xterm.js + Socket.IO クライアント)
└── README.md            # このファイル
```

---

## 技術詳細

### 通信フロー

```
Browser (xterm.js)
  ↕ WebSocket (Socket.IO)
Flask + SocketIO (monitor/app.py)
  ↕ SSH (paramiko)
M5Stack デバイス (10.0.0.1 〜 10.0.0.100)
```

### WebSocket イベント一覧

**Terminal 関連:**

| イベント | 方向 | 説明 |
|---------|------|------|
| `ssh_connect` | Client → Server | SSH 接続開始 (`{device_id}`) |
| `ssh_input` | Client → Server | キー入力の転送 (`{data}`) |
| `ssh_resize` | Client → Server | ターミナルリサイズ (`{cols, rows}`) |
| `ssh_disconnect` | Client → Server | 切断要求 |
| `ssh_connected` | Server → Client | 接続成功 (`{device_id, host}`) |
| `ssh_output` | Server → Client | ターミナル出力 (`{data}`) |
| `ssh_disconnected` | Server → Client | 切断完了 |
| `ssh_error` | Server → Client | エラー (`{message}`) |

**Broadcast 関連:**

| イベント | 方向 | 説明 |
|---------|------|------|
| `broadcast_command` | Client → Server | コマンド実行要求 (`{command, scope, scope_value}`) |
| `broadcast_start` | Server → Client | 実行開始 (`{total, command, scope}`) |
| `broadcast_result` | Server → Client | 各デバイスの結果（逐次） |
| `broadcast_done` | Server → Client | 全台完了 (`{total, success, failed}`) |
| `broadcast_error` | Server → Client | エラー (`{message}`) |

### セキュリティに関する注意

- このモニターは **信頼されたローカルネットワーク内** での運用を想定しています
- 外部公開する場合は、リバースプロキシ（nginx 等）で HTTPS + Basic 認証を追加してください
- SSH パスワードは起動引数で渡されるため、`ps` コマンドで見える可能性があります。本番では鍵認証を使用してください
- `--debug` フラグは開発時のみ使用してください
