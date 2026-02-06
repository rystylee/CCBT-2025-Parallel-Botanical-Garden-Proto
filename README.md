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
- **タイムスタンプ管理**: データの鮮度管理と時系列順処理
- **デバイスタイプ切り替え**: 1st_BI（人間+BI入力）と2nd_BI（BI入力のみ）

### 動作環境

- **ハードウェア**: M5Stack LLM630 Compute Kit
- **OS**: Ubuntu (ARM64)
- **言語**: Python 3.10以上
- **通信**: OSC (UDP), TCP

### システム構成

```
[人間の入力]          [他のBIデバイス]
    ↓ OSC                 ↓ OSC
[1st BI Device] ←→ [2nd BI Device] ←→ [2nd BI Device]
    ↓                     ↓                 ↓
  音声出力              音声出力           音声出力
```

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
├── main.py                 # エントリーポイント
├── app/                    # アプリケーション層
│   ├── __init__.py
│   └── controller.py       # AppController - OSCサーバー管理
├── bi/                     # BI関連モジュール
│   ├── __init__.py
│   ├── controller.py       # BIController - サイクル制御
│   ├── models.py           # BIInputData データクラス
│   └── utils.py            # Soft Prefix生成
├── api/                    # API層
│   ├── llm.py              # LLMクライアント
│   ├── tts.py              # TTSクライアント
│   ├── osc.py              # OSCサーバー/クライアント
│   └── utils.py            # LLM/TTS設定
├── stackflow/              # StackFlow通信
│   └── utils.py
├── config/                 # 設定ファイル
│   └── config.json
├── tests/                  # テストスクリプト
│   ├── test_bi.py
│   └── test_multi_target.py
├── scripts/                # インストール/セットアップ
└── docs/                   # ドキュメント
```

---

## 設定ファイル

[config/config.json](config/config.json) の主要セクション：

```json
{
  "device": {
    "type": "1st_BI"  // "1st_BI" (人間+BI入力) or "2nd_BI" (BI入力のみ)
  },
  "cycle": {
    "receive_duration": 3.0,   // 入力受付期間（秒）
    "rest_duration": 1.0,      // 休息期間（秒）
    "max_data_age": 60.0       // データ有効期限（秒）
  },
  "targets": [
    {"host": "192.168.1.101", "port": 8000}  // 送信先BIデバイス
  ],
  "osc": {
    "receive_port": 8000
  },
  "common": {
    "lang": "ja"  // "ja", "en", "zh", "fr"
  },
  "stack_flow_llm": {
    "max_tokens": 64
  }
}
```

### 主な設定項目

- **device.type**: デバイスタイプ
  - `1st_BI`: 人間の入力とBIからの入力の両方を受け付ける
  - `2nd_BI`: BIからの入力のみを受け付ける
- **cycle**: サイクル設定
  - `receive_duration`: 入力受付期間
  - `rest_duration`: 休息期間
  - `max_data_age`: データ有効期限（古いデータは自動破棄）
- **targets**: 送信先BIデバイスのリスト
- **common.lang**: デフォルト言語（日本語、英語、中国語、フランス語）

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
cd /root
git clone <repository-url> CCBT-2025-Parallel-Botanical-Garden-Proto
cd CCBT-2025-Parallel-Botanical-Garden-Proto

# 3. インストールスクリプトを実行
chmod +x scripts/install.sh
./scripts/install.sh

# 4. ソフトプリフィックスをダウンロード
./scripts/download_and_install_soft_prefix.sh

# 5. （オプション）翻訳パッケージをインストール
./scripts/install_argostranslate_packages.sh

# 6. 設定ファイルを編集
vi config/config.json
# IPアドレスとターゲットデバイスを設定
```

---

## 起動方法

### 通常起動

```bash
# M5Stackに接続
adb shell
cd /root/CCBT-2025-Parallel-Botanical-Garden-Proto

# アプリケーションを起動
uv run python main.py
```

起動ログ例：
```
INFO: Initialize App Controller...
INFO: Initialize BI Controller...
INFO: BI Controller initialized as 1st_BI
INFO: Starting OSC server
INFO: OSC Server started on 0.0.0.0:8000
```

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
| `/bi/input` | timestamp, text, source_type, lang | 入力データ受付 |
| `/bi/start` | なし | サイクル開始 |
| `/bi/stop` | なし | サイクル停止 |
| `/bi/status` | なし | ステータス取得 |

### `/bi/input` の引数

- `timestamp` (float): UNIXタイムスタンプ（秒）
- `text` (str): テキストデータ
- `source_type` (str): "human" または "BI"
- `lang` (str): 言語コード（`ja`, `en`, `zh`, `fr`）

---

## 使用例

### Python OSCクライアントから操作

```python
from pythonosc import udp_client
import time

# クライアント作成
client = udp_client.SimpleUDPClient("192.168.1.100", 8000)

# 1. BIサイクル開始
client.send_message("/bi/start", [])

# 2. 入力データ送信
timestamp = time.time()
client.send_message("/bi/input", [timestamp, "こんにちは", "human", "ja"])

# 3. ステータス確認
client.send_message("/bi/status", [])

# 4. サイクル停止
client.send_message("/bi/stop", [])
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

```toml
[project]
dependencies = [
    "argostranslate>=1.9.6",    # オフライン翻訳
    "googletrans>=4.0.2",       # Google翻訳API
    "loguru>=0.7.3",            # ロギング
    "python-osc>=1.9.3",        # OSCプロトコル
]
```

### StackFlowモデル

```bash
# LLMモデル
apt install llm-model-qwen2.5-0.5b-prefill-ax630c

# TTSモデル
apt install llm-model-melotts-ja-jp
apt install llm-model-melotts-en-us
apt install llm-model-melotts-zh-cn
```

### 翻訳パッケージ

argostranslateパッケージ（オフライン翻訳用）：
- `en_ja`: 英語→日本語
- `ja_en`: 日本語→英語
- `zh_ja`: 中国語→日本語
- `fr_ja`: フランス語→日本語

---

## ライセンス

（ライセンス情報を追加してください）
