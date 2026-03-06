# RunPod リモート音声変換パイプライン

M5Stack デバイス群で生成されたテキストを RunPod 上の MeloTTS + Seed-VC で音声変換するパイプライン。

## アーキテクチャ

```
M5Stack (10.0.0.1~100)          Ubuntu (10.0.0.200)              RunPod (GPU)
┌──────────────┐     OSC       ┌───────────────────┐    SCP     ┌────────────────────────┐
│  BIController │──/mixer────▶│  ubuntu_sender.py  │──.json──▶│  runpod_a_make_voice.py │
│  生成テキスト  │             │  (OSC受信→SCP転送)  │           │  (MeloTTS→Seed-VC)     │
└──────────────┘              │                    │           │                        │
                              │  ubuntu_puller.py  │◀──.wav───│  outputs/              │
                              │  (結果WAV取得)      │    SCP    │                        │
                              └───────────────────┘           └────────────────────────┘
```

## ファイル構成

| ファイル | 実行場所 | 役割 |
|---------|---------|------|
| `runpod_config.json` | 共通 | SSH接続・パス・ポートの設定 |
| `ssh_helper.py` | Ubuntu | SSH/SCP共通ユーティリティ |
| `runpod_manager.py` | Ubuntu | RunPod環境構築・デプロイ・起動管理 |
| `ubuntu_sender.py` | Ubuntu | OSC受信→RunPodへJSON送信 |
| `ubuntu_puller.py` | Ubuntu | RunPodからVC結果WAVを取得 |
| `runpod_a_make_voice.py` | RunPod | MeloTTS + Seed-VC ワーカー |
| `start_runpod_pipeline.sh` | Ubuntu | 一括起動スクリプト |

## セットアップ

### 1. SSH鍵の確認

```bash
# Ubuntu側で接続テスト
ssh dmw81eq7mnro4b-644113b7@ssh.runpod.io -i ~/.ssh/id_ed25519
```

### 2. Ubuntu 側の環境構築

```bash
cd runpod/
bash setup_ubuntu_venv.sh
source .venv/bin/activate
```

### 3. RunPod環境構築 (初回のみ)

```bash
# MeloTTS + Seed-VC をインストール
python3 runpod_manager.py setup

# nainiku.mp3 をアップロード (初回のみ)
scp -i ~/.ssh/id_ed25519 audio/nainiku.mp3 \
    dmw81eq7mnro4b-644113b7@ssh.runpod.io:/workspace/audio/nainiku.mp3
```

### 4. 接続確認

```bash
python3 runpod_manager.py check
```

## 使い方

### 一括起動 (推奨)

```bash
./start_runpod_pipeline.sh
```

これにより以下が順番に実行される:
1. RunPod接続確認
2. ワーカースクリプトのデプロイ & tmux起動
3. puller (バックグラウンド)
4. sender (フォアグラウンド、Ctrl+Cで全停止)

### 個別起動

```bash
# Step 1: ワーカー デプロイ & 起動
python3 runpod_manager.py run

# Step 2: (ターミナル1) sender
python3 ubuntu_sender.py

# Step 3: (ターミナル2) puller
python3 ubuntu_puller.py
python3 ubuntu_puller.py --play  # 取得後に再生
```

### 管理コマンド

```bash
python3 runpod_manager.py check   # 接続 & GPU確認
python3 runpod_manager.py deploy  # コードだけデプロイ
python3 runpod_manager.py start   # ワーカー起動
python3 runpod_manager.py stop    # ワーカー停止
python3 runpod_manager.py logs    # ログ確認
```

### テスト送信

```bash
# dry-run (ローカル保存のみ、RunPodへは送信しない)
python3 ubuntu_sender.py --dry-run

# 別ターミナルからOSCテスト送信
python3 -c "
from pythonosc.udp_client import SimpleUDPClient
c = SimpleUDPClient('127.0.0.1', 8000)
c.send_message('/mixer', 'これはテストです。植物の知性は静かに眠る。')
"
```

## 設定 (runpod_config.json)

主な設定項目:

- `ssh.user` / `ssh.host`: RunPod SSH接続先
- `ssh.key`: SSH鍵パス
- `runpod.osc_json_dir`: RunPod上のJSON受信ディレクトリ
- `runpod.vc_out_dir`: RunPod上のVC出力ディレクトリ
- `ubuntu_sender.osc_listen_port`: M5Stackからの受信ポート (8000)
- `ubuntu_puller.local_output_dir`: 取得WAVの保存先
- `ubuntu_puller.remove_remote_after_pull`: 取得後にリモート削除するか

## 依存関係

Ubuntu側:
```bash
bash setup_ubuntu_venv.sh   # venv作成 + python-osc インストール
```

RunPod側 (runpod_manager.py setup で自動インストール):
- MeloTTS
- Seed-VC + requirements
