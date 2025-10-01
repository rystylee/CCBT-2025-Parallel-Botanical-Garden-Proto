# CCBT-2025-Parallel-Botanical-Garden-Proto

## 1. システム概要

### 1.1 目的
M5Stack LLM630 Compute Kit上で動作し、OSC（Open Sound Control）プロトコル経由で受信したメッセージに対して、Stack Flowを使用したLLMによる文章生成とTTS（Text-to-Speech）による音声合成を行うシステムを構築する。

### 1.2 動作環境
- **ハードウェア**: M5Stack LLM630 Compute Kit
- **開発言語**: Python
- **ネットワーク**: Wi-Fi接続必須
- **プロトコル**: OSC over UDP
- **LLM/TTSサービス**: Stack Flow (M5Stack LLM630 Compute Kit内蔵)
- **設定管理**: GitHub経由で内部ストレージに配置

### 1.3 システム構成図
```
[OSCクライアント] 
    ↓ OSCメッセージ (UDP)
[LLM630 Compute Kit]
    ├── OSCレシーバー
    ├── Stack Flow LLM API
    ├── Stack Flow TTS API
    └── 設定管理 (config.json)
```

## 2. 機能仕様

### 2.1 Stack Flow LLM API機能

#### 2.1.1 基本仕様
- **入力**: テキスト文字列（UTF-8）
- **出力**: 生成されたテキスト文字列（UTF-8）
- **処理内容**: 
  - 入力テキストをプロンプトとしてStack Flow LLM APIへ送信
  - レスポンスとして生成されたテキストを取得

### 2.2 Stack Flow TTS API機能

#### 2.2.1 基本仕様
- **入力**: テキスト文字列（UTF-8）
- **出力**: 音声再生（外部スピーカー経由）
- **処理内容**:
  - テキストをStack Flow TTS APIへ送信
  - 音声データを取得・再生

### 2.3 OSCモジュール

#### 2.3.1 基本仕様
- **プロトコル**: OSC over UDP
- **受信ポート**: 設定ファイルで指定（デフォルト: 8000）
- **メッセージ形式**: 
  - アドレスパターン: `/process` 
  - 引数: 文字列型（UTF-8）

#### 2.3.2 OSCメッセージ仕様
| アドレス | 引数 | 動作 |
|---------|------|------|
| `/process` | string: prompt | LLM API → TTS API の順に実行 |

### 2.4 設定ファイル

#### 2.4.1 ファイル仕様
- **形式**: JSON
- **文字コード**: UTF-8
- **ファイル名**: `config.json`
- **保存場所**: 内部ストレージ（GitHubリポジトリから取得）

#### 2.4.2 設定項目
```json
{
  "network": {
    "device_name": "M5Stack-LLM-01",
    "ip_address": "your ip address"
  },
  
  "osc": {
    "receive_port": 8000,
    "send_port": 8001,
    "client_address": "client ip address",
  },
  
  "stack_flow_llm": {
    "model": "llm model name",
    "max_tokens": 1023,
    "system_prompt": "You are a helpful assistant.",
  },
  
  "stack_flow_tts": {
    "model": "tts model name"
  },
  
  "system": {
    "debug_mode": false,
    "log_level": "INFO"
  }
}
```

## 7. 依存関係

### 7.1 Ubuntuパッケージ
```
apt install git
apt install curl
apt install jq
```

### 7.2 Pythonパッケージ (requirements.txt)
```
loguru==0.7.3
python-osc==1.9.3
```

### 7.3 M5Stack LLM Module固有ライブラリ
```
apt install 
```
<!-- ## 8. トラブルシューティング

### 8.1 よくある問題と対処法

| 問題 | 原因 | 対処法 |
|------|------|---------|
| OSCメッセージが受信できない | ファイアウォール/ポート番号誤り | ポート開放確認、config.json確認 |
| LLM応答が遅い | ネットワーク遅延/モデルサイズ | timeout値調整、軽量モデル使用 |
| TTSが再生されない | 音量設定/スピーカー接続 | config.json音量確認 | -->
