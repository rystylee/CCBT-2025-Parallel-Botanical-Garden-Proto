# BI Monitor

Parallel Botanical Garden の全デバイス（100台・10クラスタ）を Web ブラウザから管理するためのモニターアプリケーションです。

---

## ページ一覧

| URL | 名前 | 機能 |
|-----|------|------|
| `/` | 01 SYSTEM | ping / inet / git pull / reboot |
| `/led` | 02 LED | LED 点灯確認（フェードアップ→ダウン） |
| `/sound` | 03 SOUND | サウンドチェック（tinyplay） |
| `/llm` | 04 LLM | LLM ロード検証（tmux） |
| `/tts` | 05 TTS | TTS ロード検証（tmux） |
| `/run` | 99 RUN | スクリプト実行（tmux、テスト送信付き） |
| `/terminal` | SSH TERMINAL | 対話型 SSH ターミナル |
| `/broadcast` | BROADCAST | コマンド一斉送信 |

---

## セットアップ

### 依存パッケージ

```bash
pip install flask flask-socketio paramiko python-osc
```

### 起動

```bash
python app.py
```

起動時に SSH パスワードの入力を求められます（`getpass`）。入力後、`http://localhost:5050` でアクセスできます。

---

## 新機能: SSH TERMINAL (`/terminal`)

ブラウザ内で xterm.js ベースのフルターミナルが動作します。選択したデバイスに SSH 接続し、通常のターミナルと同じ操作が可能です。

- パッケージのインストール（`pip install ...`）
- ログの確認（`journalctl`, `tail -f` 等）
- プロセス管理（`systemctl`, `ps`, `kill`）
- ファイル編集（`vim`, `nano`）
- Git 操作

### 使い方

1. ドロップダウンからデバイスを選択
2. **CONNECT** をクリック
3. ターミナルで自由に操作
4. 終了したら **DISCONNECT**

---

## 新機能: BROADCAST (`/broadcast`)

Terminal でデバッグ・検証したコマンドを、他のノードやクラスタ・全体に一括送信します。

### スコープ選択

| スコープ | 説明 | 例 |
|---------|------|----|
| All | 全100台に並列実行 | `uname -a` |
| Cluster | 指定クラスタの10台 | Cluster 3 を選択 |
| Node | 個別指定（範囲記法可） | `1,2,3` / `1-10` / `1-5,8,20-25` |

### 結果表示

- リアルタイムにストリーミングで返ってくる
- 成功（緑）/ 失敗（赤）がステータスドットで判別可能
- クリックで stdout / stderr を展開
- 実行時間・exit code を表示

### Snippets

よく使うコマンドを名前を付けて保存・再利用できます。デフォルトで以下が登録済みです:

- System info — `uname -a && uptime`
- Disk usage — `df -h /`
- Service status — `systemctl status pbg`
- Last 50 logs — `journalctl` / `tail /tmp/bi_run.log`
- Python packages — `pip list`
- Network — `ip addr show`
- Git status — `git log --oneline -5`
- Restart BI — `tmux kill-session -t bi_main`

---

## 典型的なワークフロー

### ① 特定デバイスのデバッグ

1. 既存ページ（SYSTEM / RUN 等）で問題のあるノードを特定
2. `/terminal` に移動 → そのノードに SSH 接続
3. ターミナルで自由にデバッグ（ログ確認、設定変更、パッケージ追加など）
4. 問題を特定・解決したら DISCONNECT

### ② デバッグ結果を全体に展開

1. Terminal で検証済みのコマンドをコピー
2. `/broadcast` に移動
3. コマンドをテキストエリアに貼り付け
4. スコープを選択（例: まず同じクラスタでテスト → 問題なければ All）
5. **EXECUTE** で一斉実行
6. 結果をリアルタイムで確認
7. 必要に応じて **SAVE** でスニペットとして保存

---

## 技術詳細

### SSH 接続方式

| 機能 | 方式 | 理由 |
|------|------|------|
| 既存ページ（SYSTEM, LED, RUN 等） | `sshpass` + `ssh` (subprocess) | ControlMaster による接続多重化 |
| Terminal（対話型） | `paramiko` (WebSocket経由) | リアルタイム双方向通信が必要 |
| Broadcast | `sshpass` + `ssh` (subprocess) | 既存の `ssh_run()` を再利用 |

### 通信フロー（Terminal）

```
Browser (xterm.js)
  ↕ WebSocket (Socket.IO)
Flask + SocketIO (app.py)
  ↕ SSH (paramiko)
M5Stack デバイス (10.0.0.1 〜 10.0.0.100)
```

### 通信フロー（Broadcast）

```
Browser
  ↕ WebSocket (Socket.IO)
Flask + SocketIO (app.py)
  ↕ sshpass + ssh (subprocess, 並列スレッド)
M5Stack デバイス (10.0.0.1 〜 10.0.0.100)
```
