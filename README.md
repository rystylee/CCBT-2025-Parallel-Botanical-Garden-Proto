# CCBT-2025-Parallel-Botanical-Garden-Proto

## 📚 ドキュメント

- **[要件定義書](docs/requirements.md)** - 機能要件、非機能要件、システム要件の詳細
- **[実装計画書](docs/plan.md)** - アーキテクチャ設計、実装フェーズ、技術詳細
- **[タスクリスト](docs/tasks.md)** - 開発・改善タスクの管理

## 1. システム概要

### 1.1 目的
M5Stack LLM630 Compute Kit上で動作し、OSC（Open Sound Control）プロトコル経由で受信したメッセージに対して、StackFlowを使用したLLMによる詩的テキスト生成とTTS（Text-to-Speech）による音声合成を行うシステムを構築する。

### 1.2 主な特徴
- **オンデバイスLLM推論**: クラウド不要のローカルAI処理
- **多言語対応**: 日本語、英語、中国語、フランス語をサポート
- **リアルタイム処理**: ストリーミング形式での高速レスポンス
- **柔軟なOSC通信**: 複数エンドポイントによる多様な処理パターン
- **ソフトプリフィックス対応**: モデル出力の柔軟な制御

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
```
[OSCクライアント]
    ↓ OSCメッセージ (UDP:8000)
[M5Stack LLM630 Compute Kit]
    ├── Pythonアプリケーション
    │   ├── OSCサーバー (api/osc.py)
    │   ├── AppController (app.py)
    │   ├── LLMクライアント (api/llm.py)
    │   └── TTSクライアント (api/tts.py)
    │
    └── StackFlow API (TCP:10001)
        ├── LLM推論 (Qwen2.5, Llama3.2)
        └── TTS合成 (MeloTTS)
```

---

## 2. 機能仕様

### 2.1 LLM推論機能

#### 2.1.1 基本仕様
- **入力**: テキスト文字列（UTF-8）
- **出力**: 詩的な短文（UTF-8、最大128トークン）
- **処理方式**: ストリーミング形式（トークン単位）
- **対応言語**: 日本語、英語、中国語、フランス語
- **処理内容**:
  - 入力テキストの言語を検出・翻訳（必要に応じて）
  - システムプロンプト + インストラクションプロンプト付与
  - ソフトプリフィックス適用（オプション）
  - StackFlow LLM APIへ送信
  - ストリーミングレスポンスを受信・結合

#### 2.1.2 使用モデル
- **デフォルト**: `qwen2.5-0.5B-prefill-20e`
- **その他**: `llama3.2-1b-prefill-ax630c` など

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

| アドレス | 引数 | 動作 | 実装状態 |
|---------|------|------|---------|
| `/process` | text, lang, [prefix_idx] | LLM生成 + TTS音声出力 | ✅ 実装済み |
| `/process/llm` | text, lang, [prefix_idx] | LLM生成のみ | ✅ 実装済み |
| `/process/tts` | text, lang | TTS音声出力のみ | ✅ 実装済み |
| `/reload/llm` | なし | LLMモデルリロード | ⚠️ 未実装 |
| `/reload/tts` | なし | TTSモデルリロード | ⚠️ 未実装 |
| `/ae/detect` | なし | ランダムポエティック生成 | ✅ 実装済み |

**引数の説明**:
- `text` (str): 処理するテキスト
- `lang` (str): 言語コード（`ja`, `en`, `zh`, `fr`）
- `prefix_idx` (int, optional): ソフトプリフィックスインデックス（0-9）

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

  "osc": {
    "receive_port": 8000,
    "send_port": 8000,
    "client_address": ["10.0.0.2"]
  },

  "common": {
    "lang": "ja"
  },

  "stack_flow_llm": {
    "max_tokens": 128
  },

  "stack_flow_tts": {},

  "system": {
    "debug_mode": false,
    "log_level": "INFO"
  }
}
```

**設定項目の説明**:
- `network.device_name`: デバイス名
- `network.ip_address`: M5StackのIPアドレス
- `osc.receive_port`: OSC受信ポート
- `osc.send_port`: OSC送信ポート
- `osc.client_address`: OSC送信先アドレス（配列）
- `common.lang`: デフォルト言語（`ja`, `en`, `zh`, `fr`）
- `stack_flow_llm.max_tokens`: LLM最大トークン数
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

### 6.1 test.pyの使い方

開発用のOSCテストクライアント `test.py` を使用して、アプリケーションの動作確認ができます。

#### 基本的な使い方

```bash
# ローカルPCから実行（M5StackのIPアドレスを指定）
uv run python test.py --ip <M5StackのIPアドレス> --port 8000 --message "こんにちは"
```

#### オプション

| オプション | デフォルト値 | 説明 |
|-----------|-------------|------|
| `--ip` | 127.0.0.1 | M5StackのIPアドレス |
| `--port` | 8000 | OSC受信ポート |
| `--address` | `/process` | OSCアドレスパターン |
| `--message` | "" | 送信するメッセージ |

#### 使用例

```bash
# 1. LLM生成 + TTS音声出力（日本語）
uv run python test.py \
    --ip 192.168.151.31 \
    --address /process \
    --message "こんにちは" "ja"

# 2. LLM生成のみ（音声出力なし）
uv run python test.py \
    --ip 192.168.151.31 \
    --address /process/llm \
    --message "短い詩を書いて" "ja"

# 3. TTS音声出力のみ
uv run python test.py \
    --ip 192.168.151.31 \
    --address /process/tts \
    --message "これはテストです" "ja"

# 4. ランダムポエティック生成
uv run python test.py \
    --ip 192.168.151.31 \
    --address /ae/detect

# 5. 英語で処理
uv run python test.py \
    --ip 192.168.151.31 \
    --address /process \
    --message "hello world" "en"
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
| 2025-02-06 | v0.1.0 | 初版リリース、基本機能実装完了 |
