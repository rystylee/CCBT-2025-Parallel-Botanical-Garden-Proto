# CCBT-2025-Parallel-Botanical-Garden-Proto

M5Stack LLM Compute Kit上で動作する分散型Botanical Intelligence (BI)システム。複数のBIデバイスがOSC経由で相互通信しながら、LLMによる協調的な詩的テキスト生成とTTSによる音声出力を行います。

---

## ドキュメント

- [要件定義書](docs/requirements.md) - システム仕様と機能要件
- [実装計画書](docs/plan.md) - アーキテクチャと実装状況
- [タスクリスト](docs/tasks.md) - 開発タスク管理

---

## システム概要

### 主な特徴

- **分散型サイクルシステム**: 独立した4段階のサイクル（受信→生成→出力→休息）
- **協調的テキスト生成**: 複数デバイス間でのテキストリレー
- **オンデバイスLLM推論**: クラウド不要のローカルAI処理（2~3トークン生成）
- **伝達回数管理**: `relay_count`による循環制御と寿命管理
- **柔軟な入力受付**: 全てのデバイスが人間とBIの両方の入力を受け付け可能
- **音響エフェクト処理**: Jóhann Jóhannsson風「Accumulating Ghosts」パイプライン
- **LED制御**: PCA9685経由のフェードアニメーション
- **植物センサー統合**: クロロフィル蛍光（CF）×Acoustic Emission（AE）によるSoft Prefix制御
- **デバイスID自動検出**: `/etc/ccbt-device-id`または`/etc/network/interfaces`から自動取得
- **言語自動検出**: デバイスIDの末尾数字から6言語（ja/en/fr/fa/ar/zh）を自動決定

### 動作環境

- **ハードウェア**: M5Stack LLM630 Compute Kit
- **OS**: Ubuntu (ARM64)
- **言語**: Python 3.10以上
- **通信**: OSC (UDP), TCP

### システム構成

```
[人間の入力]          [他のBIデバイス]
    ↓ OSC                 ↓ OSC
[BI Device A] ←→ [BI Device B] ←→ [BI Device C]
    ↓                     ↓                 ↓
  音声出力              音声出力           音声出力
```

**注意**: 全てのBIデバイスは同一の動作を行い、人間とBIの両方の入力を受け付けます。

### BIサイクル

```
┌────────────┐
│  RECEIVING │ (3秒) - OSC経由で入力データ受付
└──────┬─────┘
       ↓
┌─────────────┐
│ GENERATING  │ - データ連結、LLMで2~3トークン生成
└──────┬──────┘
       ↓
┌─────────────┐
│   OUTPUT    │ - OSC送信、TTS音声再生
└──────┬──────┘
       ↓
┌─────────────┐
│   RESTING   │ (1秒) - 待機
└──────┬──────┘
       ↓
   (RECEIVINGに戻る)
```

---

## プロジェクト構造

```
CCBT-2025-Parallel-Botanical-Garden-Proto/
├── main.py                        # エントリーポイント
├── pca9685_osc_led_server.py      # PCA9685 LED制御サーバー
├── app/                           # アプリケーション層
│   ├── __init__.py
│   └── controller.py              # AppController - OSCサーバー管理
├── bi/                            # BI関連モジュール
│   ├── __init__.py
│   ├── controller.py              # BIController - サイクル制御
│   ├── models.py                  # BIInputData データクラス
│   └── utils.py                   # Soft Prefix生成
├── api/                           # API層
│   ├── llm.py                     # LLMクライアント
│   ├── tts.py                     # TTSクライアント
│   ├── osc.py                     # OSCサーバー/クライアント
│   ├── audio_effects.py           # 音響エフェクト処理（Ghost/Reverb/Mastering）
│   ├── text_transform.py          # テキスト変換（ひらがな化、母音伸ばし）
│   └── utils.py                   # LLM/TTS設定、NGワードフィルタ
├── stackflow/                     # StackFlow通信
│   └── utils.py
├── utils/                         # ユーティリティ
│   ├── __init__.py
│   └── network_config.py          # ネットワーク設定CSV読み込み
├── input_controller/              # 入力制御システム
│   ├── input_controller.py        # STT + センサー入力
│   ├── bi_input_sender.py         # OSC送信
│   └── input_config.example.json  # 設定例
├── monitor/                       # Web管理UI
│   ├── app.py                     # Flask + SocketIOサーバー
│   ├── templates/                 # HTMLテンプレート
│   └── static/                    # 静的ファイル
├── runpod/                        # RunPod統合（クラウドVC）
│   └── README.md
├── systemd/                       # systemd自動起動設定
│   ├── ccbt-audio-keepalive.service
│   └── ccbt-bi-check.service
├── tools/                         # 開発ツール
├── config/                        # 設定ファイル
│   ├── config.json                # メイン設定
│   ├── networks.csv               # ネットワーク設定
│   ├── plant_sensor_config.json   # 植物センサー設定
│   └── ngwords.json               # NGワード設定
├── audio/                         # 待機音声ファイル
├── tests/                         # テストスクリプト
│   ├── test_bi.py
│   └── test_multi_target.py
├── scripts/                       # インストール/セットアップ
└── docs/                          # ドキュメント
    ├── requirements.md
    ├── plan.md
    └── tasks.md
```

---

## 設定ファイル

### config/config.json

デバイス固有の設定：

```json
{
  "network": {
    "csv_path": "config/networks.csv"  // ネットワーク設定CSVのパス
    // device_idは自動検出（/etc/ccbt-device-id または /etc/network/interfaces）
  },
  "cycle": {
    "receive_duration": 3.0,    // 入力受付期間（秒）
    "rest_duration": 1.0,       // 休息期間（秒）
    "max_relay_count": 6        // 伝達回数の上限（これ以上は破棄）
  },
  "osc": {
    "receive_port": 8000
  },
  "mixer": {
    "host": "10.0.0.200",       // Mixer PCのIPアドレス
    "port": 8000
  },
  "common": {
    "lang": "ja"  // "ja", "en", "fr", "fa", "ar", "zh"（デバイスIDから自動決定）
  },
  "stack_flow_llm": {
    "max_tokens": 64,
    "soft_prefix_vals": [0.08],
    "max_output_chars": {"ja": 20, "zh": 20, "en": 50, "fr": 50, "fa": 40, "ar": 40}
  },
  "audio": {
    "playback_device": "dmixer",
    "sample_rate": 48000,
    "channels": 2,
    "effect_mode": "ghost",     // ghost（ゴーストパイプライン）、rumble、off
    "waiting_audio_dir": "audio",
    "waiting_audio_prefix": "AE_",
    "pitch_shift": { "enabled": true, "semitones": [-3, -2, 0, 0, 2, 3] },
    "speed": { "mode": "atempo", "value": 0.8 },
    "text_transform": {
      "enabled": true,
      "to_hiragana": true,
      "elongation_mode": "mixed"
    },
    // 詳細なエフェクト設定は実際のconfig.jsonを参照
  },
  "led_control": {
    "enabled": true,
    "fade_up_duration": 15.0,
    "fade_down_duration": 15.0,
    "receiving_min_brightness": 0.0,
    "receiving_max_brightness": 0.1,
    "generating_min_brightness": 0.05,
    "generating_max_brightness": 0.25,
    // PCA9685ハードウェア設定など詳細は実際のconfig.jsonを参照
  },
  "llm_settings": {
    "ja": {
      "model": "TinySwallow-1.5B",
      "system_prompt": "植物の翻訳者。森林の詩を短い単語で紡ぐ。",
      "instruction_prompt": "続き: "
    }
    // en, fr, fa, ar, zhも同様
  }
}
```

### config/networks.csv

全デバイスのネットワーク情報を一元管理：

```csv
ID,IP,To
1,10.0.0.1,"2,5"
2,10.0.0.2,"3,6"
3,10.0.0.3,"4,7"
...
100,10.0.0.100,"91,94"
```

- **ID**: デバイスID（1-100）
- **IP**: デバイスのIPアドレス（ルール: ID X → 10.0.0.X）
- **To**: 送信先デバイスIDのカンマ区切りリスト

### 主な設定項目

- **network**: ネットワーク設定
  - `csv_path`: ネットワーク設定CSVのパス
  - デバイスIDは自動検出（`/etc/ccbt-device-id`または`/etc/network/interfaces`から取得）
- **cycle**: サイクル設定
  - `receive_duration`: 入力受付期間（秒）
  - `rest_duration`: 休息期間（秒）
  - `max_relay_count`: 伝達回数の上限（これ以上は破棄）
- **common.lang**: デフォルト言語（デバイスIDの末尾数字から自動決定: ja/en/fr/fa/ar/zh）
- **audio**: 音声出力設定
  - `effect_mode`: エフェクトモード（ghost/rumble/off）
  - `pitch_shift`: ピッチシフト設定
  - `speed`: 速度変更設定
  - `text_transform`: テキスト変換設定（ひらがな化、母音伸ばし）
- **led_control**: LED制御設定
  - `enabled`: LED制御の有効/無効
  - `fade_up_duration` / `fade_down_duration`: フェード時間
  - `receiving_*_brightness` / `generating_*_brightness`: 状態別の輝度範囲
- **llm_settings**: 言語別LLM設定（モデル、システムプロンプト、指示プロンプト）

**設定変更方法**:
- デバイスIDは自動検出されるため、手動設定は不要
- 言語もデバイスIDから自動決定されるため、手動設定は不要（オーバーライド可能）
- IPアドレスと送信先はnetworks.csvから自動的に解決されます

**詳細**: [docs/requirements.md](docs/requirements.md)を参照

---

## インストール

### 前提条件

- M5Stack LLM630 Compute Kit
- adb接続が確立済み
- Wi-Fi接続設定済み

### インストール手順

```bash
# 1. M5Stackに接続
adb shell

# 2. リポジトリをクローン
cd /root && mkdir dev && cd dev
git clone https://github.com/rystylee/CCBT-2025-Parallel-Botanical-Garden-Proto.git
cd CCBT-2025-Parallel-Botanical-Garden-Proto

# 3. インストールスクリプトを実行
. ./scripts/install.sh

# 4. 設定ファイルを編集
vim config/config.json
# device_id を設定（IPアドレスと送信先はnetworks.csvから自動取得）

# 5. IPアドレスを固定
vim /etc/network/interfaces
# 以下を参考に、IPアドレスを設定
---
allow-hotplug eth0
#iface eth0 inet dhcp
iface eth0 inet static
    address 10.0.0.1
    netmask 255.255.255.0
---
```

---

## 起動方法

### 通常起動

```bash
# M5Stackに接続
adb shell
cd /root/dev/CCBT-2025-Parallel-Botanical-Garden-Proto

# アプリケーションを起動
uv run python main.py
```

起動ログ例：
```
INFO: Initialize App Controller...
INFO: Initialize BI Controller...
INFO: BI Controller initialized
INFO: Auto-starting BI cycle
INFO: Starting BI cycle
INFO: Starting OSC server
INFO: OSC Server started on 0.0.0.0:8000
INFO: RECEIVING phase started
```

**注意**: BIサイクルはアプリケーション起動時に自動的に開始されます。

### バックグラウンド起動（tmux使用）

```bash
# tmuxセッションを開始（-u: UTF-8対応）
tmux new -u -s ccbt-llm

# アプリケーションを起動
uv run python main.py

# デタッチ: Ctrl+b → d

# セッションに再接続
tmux attach -u -t ccbt-llm
```

---

## OSCエンドポイント

### 受信エンドポイント（UDP: 8000）

| エンドポイント | 引数 | 機能 |
|------------|------|------|
| `/bi/input` | text, soft_prefix_b64, relay_count | 入力データ受付 |
| `/bi/soft_prefix_update` | soft_prefix_val, cf_value, ae_value | Soft Prefix更新＋LEDパフォーマンス |
| `/bi/stop` | なし | サイクル停止 |
| `/bi/status` | なし | ステータス取得 |

**注意**: サイクルはアプリケーション起動時に自動開始されるため、`/bi/start`エンドポイントは存在しません。

### エンドポイント詳細

#### `/bi/input`
- `text` (str): テキストデータ
- `soft_prefix_b64` (str): LLM推論用のsoft prefix（Base64エンコード済みbf16データ）
- `relay_count` (int): メッセージの伝達回数（0から始まる整数、max_relay_count以上で破棄）

#### `/bi/soft_prefix_update`
- `soft_prefix_val` (float): 新しいsoft prefix値
- `cf_value` (float): クロロフィル蛍光値（オプション）
- `ae_value` (float): Acoustic Emission値（オプション）
- 植物センサー統合システムから送信され、LEDパフォーマンスをトリガーします

---

## 使用例

### Python OSCクライアントから操作

```python
from pythonosc import udp_client

# クライアント作成
client = udp_client.SimpleUDPClient("192.168.1.100", 8000)

# 1. 入力データ送信
# soft_prefix_b64は事前に生成されたBase64文字列
text = "こんにちは"
soft_prefix_b64 = "<base64_encoded_soft_prefix>"
relay_count = 0
client.send_message("/bi/input", [text, soft_prefix_b64, relay_count])

# 2. ステータス確認
client.send_message("/bi/status", [])

# 3. サイクル停止（必要な場合）
client.send_message("/bi/stop", [])
```

**注意**: サイクルは自動的に開始されているため、`/bi/start`を送信する必要はありません。

### デバッグスクリプト

別のマシンから稼働中のBIデバイスに/bi/inputメッセージを送信するスクリプト:

```bash
# 基本的な使用方法（relay_count=0、ランダムなsoft prefixで送信）
python scripts/send_bi_input.py -H 192.168.1.100 -t "こんにちは"

# relay_countを指定して送信
python scripts/send_bi_input.py -H 192.168.1.100 -t "Hello world" -r 2

# カスタムsoft prefixを指定して送信
python scripts/send_bi_input.py -H 192.168.1.100 -t "World" -s "<base64_string>"

# カスタムポートを指定
python scripts/send_bi_input.py -H 192.168.1.100 -p 9000 -t "世界"

# ヘルプを表示
python scripts/send_bi_input.py --help
```

### テストスクリプトの実行

```bash
# BIサイクルのテスト
python tests/test_bi.py --host 192.168.1.100

# 複数ターゲット送信のテスト
python tests/test_multi_target.py
```

---

## 依存関係

### Pythonパッケージ

主要な依存関係（詳細は`pyproject.toml`を参照）：

- **loguru**: ロギング
- **python-osc**: OSCプロトコル
- **openai**: OpenAI互換TTS/STT API
- **numpy**: 数値演算、信号処理
- **scipy**: 科学計算、フィルタリング、音響エフェクト
- **soundfile**: 音声ファイルI/O
- **smbus2**: I2C通信（PCA9685制御用）
- **pykakasi**: ひらがな変換（オプション）
- **flask**: Web管理UI（Monitor用）
- **flask-socketio**: リアルタイム通信（Monitor用）
- **paramiko**: SSH接続（Monitor用）
- **pyserial**: シリアル通信（Input Controller用）

### StackFlowモデル

```bash
# LLMモデル
apt install llm-model-TinySwallow-1.5B

# TTSモデル（言語別）
apt install llm-model-melotts-ja-jp    # 日本語
apt install llm-model-melotts-en-us    # 英語
apt install llm-model-melotts-zh-cn    # 中国語
apt install llm-model-melotts-fr-fr    # フランス語
apt install llm-model-melotts-fa-ir    # ペルシャ語
apt install llm-model-melotts-ar-sa    # アラビア語
```

### システムコマンド

- **FFmpeg**: 音声エフェクト処理、フォーマット変換、ピッチシフト、速度変更
- **aplay** / **tinyplay**: ALSA経由での音声ファイル再生
- **i2cdetect**: I2Cデバイス検出（PCA9685用）

---

## ライセンス

（ライセンス情報を追加してください）
