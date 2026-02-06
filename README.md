# CCBT-2025-Parallel-Botanical-Garden-Proto

## 📚 ドキュメント

- **[要件定義書](docs/requirements.md)** - 機能要件、非機能要件、システム要件の詳細
- **[実装計画書](docs/plan.md)** - アーキテクチャ設計、実装フェーズ、技術詳細
- **[タスクリスト](docs/tasks.md)** - 開発・改善タスクの管理

## 1. システム概要

### 1.1 目的
M5Stack LLM630 Compute Kit上で動作する**分散型Botanical Intelligence (BI)システム**を構築する。複数のBIデバイスがOSC（Open Sound Control）プロトコル経由で相互に通信しながら、StackFlowを使用したLLMによる協調的な詩的テキスト生成（2~3トークン）とTTS（Text-to-Speech）による音声出力を行う。各デバイスは独立したサイクルで動作し、人間の入力と他のBIデバイスからの入力を受け取りながら、短い詩的表現を生成し続ける。

### 1.2 主な特徴
- **分散型サイクルシステム**: 独立した4段階のサイクル（受信→生成→出力→休息）
- **協調的テキスト生成**: 複数デバイス間でのテキストリレー
- **オンデバイスLLM推論**: クラウド不要のローカルAI処理（2~3トークン生成）
- **多言語対応**: 日本語、英語、中国語、フランス語をサポート
- **タイムスタンプ管理**: データの鮮度管理と時系列順処理
- **デバイスタイプ切り替え**: 1st_BI（人間+BI入力）と2nd_BI（BI入力のみ）

### 1.3 動作環境
- **ハードウェア**: M5Stack LLM630 Compute Kit
- **OS**: Ubuntu (ARM64)
- **開発言語**: Python 3.10以上
- **パッケージマネージャー**: uv
- **ネットワーク**: Wi-Fi接続必須
- **プロトコル**: OSC over UDP, TCP (StackFlow)
- **LLM/TTSサービス**: StackFlow (M5Stack LLM630 Compute Kit内蔵)
- **設定管理**: Git経由で管理

### 1.4 システム構成図

#### 分散BIシステム全体像
```
[人間の入力]          [他のBIデバイス]
    ↓ OSC                 ↓ OSC
[1st BI Device] ←→ [2nd BI Device] ←→ [2nd BI Device]
    ↓                     ↓                 ↓
  音声出力              音声出力           音声出力
```

#### 各BIデバイスの内部構成
```
[BIデバイス (M5Stack LLM630)]
    │
    ├── OSC受信 (UDP:8000)
    │   └── /bi/input (timestamp, text, source_type, lang)
    │
    ├── BIController (app.py)
    │   ├── RECEIVING フェーズ (3秒)
    │   ├── GENERATING フェーズ
    │   ├── OUTPUT フェーズ
    │   └── RESTING フェーズ (1秒)
    │
    ├── StackFlow API (TCP:10001)
    │   ├── LLM推論 (2~3トークン生成)
    │   └── TTS合成
    │
    └── OSC送信 (UDP:8000)
        └── /bi/input → 次のBIデバイスへ
```

---

## 2. 機能仕様

### 2.1 LLM推論機能（v2.0: 短文生成特化）

#### 2.1.1 基本仕様
- **入力**: テキスト文字列（UTF-8）
- **出力**: 詩的な短文（UTF-8、**2~3トークン**）
- **処理方式**: ストリーミング形式（トークン単位）
- **対応言語**: 日本語、英語、中国語、フランス語
- **処理内容**:
  - 複数の入力テキストを時系列順に連結
  - 入力テキストの言語を検出・翻訳（必要に応じて）
  - システムプロンプト + インストラクションプロンプト付与
  - ソフトプリフィックス適用（ランダム選択）
  - StackFlow LLM APIへ送信
  - ストリーミングレスポンスを受信・結合

#### 2.1.2 使用モデル
- **デフォルト**: `qwen2.5-0.5B-prefill-20e`（全言語対応）
- **その他**: `llama3.2-1b-prefill-ax630c` など

#### 2.1.3 プロンプト設定（v2.0）
各言語のインストラクションプロンプトは2~3トークン生成に最適化されています:

- **日本語**: "入力テキストの続きの短い詩的な言葉を日本語で生成してください。出力は必ず2~3トークン以内で生成してください。"
- **英語**: "Please generate a continuation of the input text with 2-3 tokens of poetic words in English."
- その他の言語も同様に最適化

### 2.2 TTS音声合成機能

#### 2.2.1 基本仕様
- **入力**: テキスト文字列（UTF-8）
- **出力**: 音声再生（スピーカー経由）
- **音声フォーマット**: PCMストリーム
- **音量**: 設定可能（デフォルト15%）
- **処理内容**:
  - オーディオデバイスのセットアップ
  - 言語に応じたMeloTTSモデル選択
  - StackFlow TTS APIへ送信
  - PCMストリーム受信・自動再生

#### 2.2.2 対応モデル
| 言語 | モデル名 |
|------|---------|
| 日本語 | `melotts-ja-jp` |
| 英語 | `melotts-en-us` |
| 中国語 | `melotts-zh-cn` |

### 2.3 OSC通信機能

#### 2.3.1 基本仕様
- **プロトコル**: OSC over UDP
- **受信ポート**: 設定ファイルで指定（デフォルト: 8000）
- **非同期処理**: AsyncIOOSCUDPServer使用

#### 2.3.2 対応OSCエンドポイント

**BIシステム用エンドポイント（v2.0）**

| アドレス | 引数 | 動作 | 実装状態 |
|---------|------|------|---------|
| `/bi/input` | timestamp, text, source_type, lang | 入力データ受付（人間・BI両方） | ✅ 実装済み |
| `/bi/start` | なし | BIサイクル開始 | ✅ 実装済み |
| `/bi/stop` | なし | BIサイクル停止 | ✅ 実装済み |
| `/bi/status` | なし | ステータス取得 | ✅ 実装済み |

**引数の説明**:
- `timestamp` (float): UNIXタイムスタンプ（秒）
- `text` (str): テキストデータ
- `source_type` (str): "human" または "BI"
- `lang` (str): 言語コード（`ja`, `en`, `zh`, `fr`）

### 2.4 翻訳機能

#### 2.4.1 基本仕様
- **ライブラリ**: argostranslate（オフライン翻訳）
- **フォールバック**: googletrans（オンライン翻訳）
- **対応言語ペア**: en↔ja, zh↔ja, fr↔ja など

---

## 3. 設定ファイル

### 3.1 ファイル仕様
- **ファイル名**: `config/config.json`
- **形式**: JSON
- **文字コード**: UTF-8

### 3.2 設定項目

```json
{
  "network": {
    "device_name": "M5Stack-LLM-01",
    "ip_address": "192.168.151.31"
  },

  "device": {
    "type": "1st_BI",
    "_note": "Set to '1st_BI' (accepts human+BI input) or '2nd_BI' (accepts only BI input)"
  },

  "cycle": {
    "receive_duration": 3.0,
    "rest_duration": 1.0,
    "max_data_age": 60.0
  },

  "targets": [
    {
      "host": "192.168.151.32",
      "port": 8000
    }
  ],

  "osc": {
    "receive_port": 8000,
    "client_address": ["10.0.0.2"]
  },

  "common": {
    "lang": "ja"
  },

  "stack_flow_llm": {
    "max_tokens": 3
  },

  "stack_flow_tts": {},

  "system": {
    "debug_mode": false,
    "log_level": "INFO"
  }
}
```

**設定項目の説明**:

**ネットワーク設定**:
- `network.device_name`: デバイス名
- `network.ip_address`: M5StackのIPアドレス

**デバイス設定（v2.0）**:
- `device.type`: デバイスタイプ（`"1st_BI"` または `"2nd_BI"`）
  - `1st_BI`: 人間の入力とBIからの入力の両方を受け付ける
  - `2nd_BI`: BIからの入力のみを受け付ける（人間の入力は無視）

**サイクル設定（v2.0）**:
- `cycle.receive_duration`: 入力受付期間（秒）
- `cycle.rest_duration`: 休息期間（秒）
- `cycle.max_data_age`: データ有効期限（秒、デフォルト60秒）

**ターゲット設定（v2.0）**:
- `targets`: 送信先BIデバイスのリスト
  - `host`: ターゲットのIPアドレス
  - `port`: ターゲットのOSCポート

**OSC設定**:
- `osc.receive_port`: OSC受信ポート
  - 送信ポートは `targets` の各デバイスで個別に指定

**共通設定**:
- `common.lang`: デフォルト言語（`ja`, `en`, `zh`, `fr`）

**StackFlow設定**:
- `stack_flow_llm.max_tokens`: LLM最大トークン数（v2.0では3に設定）

**システム設定**:
- `system.debug_mode`: デバッグモード有効化
- `system.log_level`: ログレベル（`DEBUG`, `INFO`, `WARNING`, `ERROR`）

---

## 4. インストール

### 4.1 前提条件
- M5Stack LLM630 Compute Kit
- adb接続が確立済み
- Wi-Fi接続設定済み

### 4.2 インストール手順

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

# 4. 翻訳パッケージをインストール
./scripts/install_argostranslate_packages.sh

# 5. （オプション）ソフトプリフィックスをダウンロード
./scripts/download_and_install_soft_prefix.sh

# 6. 設定ファイルを編集
vi config/config.json
# IPアドレスとOSCクライアントアドレスを設定
```

---

## 5. 起動方法

### 5.1 アプリケーションの起動

```bash
# M5Stackに接続
adb shell
cd /root/CCBT-2025-Parallel-Botanical-Garden-Proto

# アプリケーションを起動
uv run python main.py
```

起動すると、以下のログが表示されます：
```
INFO: OSC Server started on 0.0.0.0:8000
INFO: LLM Client initialized
INFO: TTS Client initialized
```

### 5.2 バックグラウンド起動（tmux使用）

```bash
# tmuxセッションを開始
tmux new -s ccbt-llm

# アプリケーションを起動
uv run python main.py

# デタッチ: Ctrl+b → d

# セッションに再接続
tmux attach -t ccbt-llm
```

---

## 6. テストクライアントの使用

### 6.1 BIシステムのテスト（v2.0）

BIシステム用のテストスクリプト `test/test_bi.py` を使用します。

#### 基本的なサイクルテスト

```bash
# BIサイクルをテスト（人間の入力とBIの入力を送信）
python test/test_bi.py --host 192.168.151.31 --test cycle
```

#### 古いデータフィルタリングのテスト

```bash
# 60秒以上古いデータが破棄されることを確認
python test/test_bi.py --host 192.168.151.31 --test filter
```

#### 2nd_BIモードのテスト

```bash
# 1. config.json の device.type を "2nd_BI" に変更
# 2. アプリケーションを再起動
# 3. テストを実行
python test/test_bi.py --host 192.168.151.31 --test 2nd_bi
```

#### 全テストの実行

```bash
python test/test_bi.py --host 192.168.151.31 --test all
```

### 6.2 手動でのOSC送信

Pythonインタラクティブシェルから手動でテスト:

```python
from pythonosc import udp_client
import time

# クライアント作成
client = udp_client.SimpleUDPClient("192.168.151.31", 8000)

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

### 6.2 TTS単体テスト

```bash
# MeloTTS単体テスト
uv run python test/tts_melotts_talk.py \
    --host localhost \
    --port 10001 \
    --model melotts-ja-jp \
    --text "宙に舞う無数の星空。"
```

---

## 7. 依存関係

### 7.1 Ubuntuパッケージ
```bash
apt install git curl jq tmux
```

### 7.2 Pythonパッケージ

pyproject.tomlに定義された依存関係：

```toml
[project]
dependencies = [
    "argostranslate>=1.9.6",
    "googletrans>=4.0.2",
    "loguru>=0.7.3",
    "openai>=1.109.1",
    "python-osc>=1.9.3",
]
```

### 7.3 StackFlowモデル

```bash
# LLMモデル
apt install llm-model-qwen2.5-1.5b-ax630c
apt install llm-model-llama3.2-1b-prefill-ax630c

# TTSモデル
apt install llm-model-melotts-ja-jp
apt install llm-model-melotts-en-us
apt install llm-model-melotts-zh-cn
```

### 7.4 翻訳パッケージ

argostranslateパッケージ（オフライン翻訳用）：
- `en_ja`: 英語→日本語
- `ja_en`: 日本語→英語
- `zh_ja`: 中国語→日本語
- `fr_ja`: フランス語→日本語

---

## 8. トラブルシューティング

### 8.1 よくある問題と対処法

| 問題 | 原因 | 対処法 |
|------|------|---------|
| OSCメッセージが受信できない | ファイアウォール/ポート設定 | `ufw allow 8000/udp`でポート開放 |
| LLM生成が開始しない | StackFlow未起動 | `systemctl status stackflow`で確認 |
| 音声が出ない | オーディオデバイス設定 | `config.json`の`playcard`/`playdevice`確認 |
| 翻訳が機能しない | 翻訳パッケージ未インストール | `install_argostranslate_packages.sh`実行 |
| メモリ不足エラー | モデルサイズ過大 | より小さいモデル（0.5B）に変更 |
| 接続エラー | StackFlow API未起動 | M5Stackを再起動 |

### 8.2 ログ確認

```bash
# アプリケーションログをリアルタイム表示
# （loguruがコンソールに出力）

# ログレベルをDEBUGに変更
# config.jsonの"log_level"を"DEBUG"に設定
```

### 8.3 デバッグモード

```bash
# config.jsonでデバッグモードを有効化
{
  "system": {
    "debug_mode": true,
    "log_level": "DEBUG"
  }
}
```

---

## 9. 開発

### 9.1 プロジェクト構造

```
CCBT-2025-Parallel-Botanical-Garden-Proto/
├── api/                    # APIモジュール
│   ├── llm.py             # LLMクライアント
│   ├── tts.py             # TTSクライアント
│   ├── osc.py             # OSCサーバー/クライアント
│   └── utils.py           # 設定定数
├── config/                 # 設定ファイル
│   └── config.json        # アプリケーション設定
├── docs/                   # ドキュメント
│   ├── requirements.md    # 要件定義書
│   ├── plan.md            # 実装計画書
│   └── tasks.md           # タスクリスト
├── stackflow/              # StackFlow通信
│   └── utils.py           # TCP通信ユーティリティ
├── scripts/                # インストール/セットアップ
│   ├── install.sh
│   └── ...
├── test/                   # テストスクリプト
│   └── tts_melotts_talk.py
├── main.py                 # エントリーポイント
├── app.py                  # アプリケーションコントローラー
├── test.py                 # OSCテストクライアント
├── pyproject.toml          # プロジェクト設定
└── README.md               # このファイル
```

### 9.2 開発ルール

CLAUDE.mdに記載された開発ルールに従ってください：
- 日本語で会話
- 各技術やツールは最新情報をMCPやWeb検索で調査
- 適度に英語でコメントを記載
- Conventional Commits形式でコミット（英語、Claude Code署名なし）

### 9.3 コントリビューション

1. このリポジトリをフォーク
2. フィーチャーブランチを作成 (`git checkout -b feature/amazing-feature`)
3. 変更をコミット (`git commit -m 'feat: add amazing feature'`)
4. ブランチにプッシュ (`git push origin feature/amazing-feature`)
5. プルリクエストを作成

---

## 10. ライセンス

（ライセンス情報を追加してください）

---

## 11. 参考リンク

- [M5Stack LLM Compute Kit](https://docs.m5stack.com/en/compute/llm630)
- [StackFlow Documentation](https://example.com)
- [OSC Specification](https://opensoundcontrol.stanford.edu/spec-1_0.html)
- [MeloTTS](https://github.com/myshell-ai/MeloTTS)
- [argostranslate](https://github.com/argosopentech/argos-translate)

---

## 12. 作者

（作者情報を追加してください）

---

## 13. 更新履歴

| 日付 | バージョン | 変更内容 |
|------|-----------|---------|
| 2025-02-06 | v2.0.0 | 分散BIシステム実装完了、サイクルベースの協調的テキスト生成 |
| 2025-02-06 | v1.0.0 | 初版リリース、基本的なOSC-LLM-TTS機能実装完了 |
