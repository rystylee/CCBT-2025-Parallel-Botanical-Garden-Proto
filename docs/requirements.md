# 要件定義書

## 1. プロジェクト概要

### 1.1 プロジェクト名
CCBT-2025-Parallel-Botanical-Garden-Proto

### 1.2 目的
M5Stack LLM Compute Kit上で動作する分散型音声対話システム。複数のBotanical Intelligence（BI）デバイスがOSC経由で相互通信しながら、LLMによる協調的な詩的テキスト生成とTTSによる音声出力を行う。

### 1.3 動作環境
- **ハードウェア**: M5Stack LLM630 Compute Kit
- **OS**: Ubuntu (ARM64)
- **言語**: Python 3.10以上
- **通信**: OSC (UDP), TCP

---

## 2. システムアーキテクチャ

### 2.1 デバイスタイプ

**1st BI（プライマリBI）**
- マイク入力（人間の声）を受け付ける
- 他のBIデバイスからの信号も受け付ける
- 入力: `{timestamp, text(from human), text(from BI), lang}`

**2nd BI（セカンダリBI）**
- 他のBIデバイスからの信号のみを受け付ける
- 人間の入力は無視
- 入力: `{timestamp, text(from BI), lang}`

### 2.2 動作サイクル

各BIデバイスは独立した4段階のサイクルで動作：

```
1. 入力受付期間（3秒）
   ↓ OSC経由で入力データを受け付け（複数可）
   ↓ 60秒以上古いデータは自動破棄

2. 生成期間
   ↓ 入力データを時系列順に連結
   ↓ LLMで続きのテキストを生成（2~3トークン）

3. 出力期間
   ↓ 生成テキストをOSC送信（次のBIへ）
   ↓ 全入力+生成をTTS音声再生

4. 休息期間（1秒）
   ↓ 待機

→ サイクル1に戻る
```

---

## 3. 主要機能

### 3.1 LLM推論
- **モデル**: qwen2.5-0.5B-prefill-20e
- **出力**: 最大64トークン（通常2~3トークン）
- **プロンプト**: 詩的な短文生成に特化
- **Soft Prefix**: bf16形式のプリフィックスチューニング対応

### 3.2 TTS音声合成
- **モデル**: MeloTTS (日本語/英語/中国語)
- **フォーマット**: PCMストリーム
- **音量**: デフォルト15%

### 3.3 OSC通信

#### 受信エンドポイント（UDP: 8000）
| エンドポイント | 引数 | 機能 |
|------------|------|------|
| `/bi/input` | timestamp, text, source_type, lang | 入力データ受付 |
| `/bi/stop` | なし | サイクル停止 |
| `/bi/status` | なし | ステータス取得 |

**注意**: サイクルはアプリケーション起動時に自動開始されます。

#### 送信
- `/bi/input` 経由で次のBIデバイスへ生成テキストを送信
- 設定ファイル（config.json）で送信先を指定

---

## 4. 設定ファイル構造

`config/config.json` の主要セクション：

```json
{
  "device": {
    "type": "1st_BI"  // or "2nd_BI"
  },
  "cycle": {
    "receive_duration": 3.0,  // 入力受付期間（秒）
    "rest_duration": 1.0,     // 休息期間（秒）
    "max_data_age": 60.0      // データ有効期限（秒）
  },
  "targets": [
    {"host": "192.168.1.101", "port": 8000}
  ],
  "osc": {
    "receive_port": 8000
  },
  "common": {
    "lang": "ja"  // "en", "zh", "fr"
  },
  "stack_flow_llm": {
    "max_tokens": 64
  }
}
```

---

## 5. 依存関係

### Pythonライブラリ
- loguru (ロギング)
- python-osc (OSCプロトコル)
- argostranslate (オフライン翻訳)
- googletrans (Google翻訳API)

### StackFlowモデル
- llm-model-qwen2.5-0.5B-prefill-20e
- llm-model-melotts-ja-jp
- llm-model-melotts-en-us
- llm-model-melotts-zh-cn

---

## 6. 非機能要件

### 6.1 性能
- サイクル時間: 約5~8秒（3秒受付 + 生成 + 出力 + 1秒休息）
- LLM推論: 1秒以内
- TTS生成: 1秒以内に再生開始

### 6.2 信頼性
- 継続動作（無限サイクル）
- StackFlow接続エラー時の自動再接続
- loguru による詳細ログ出力

### 6.3 拡張性
- 言語追加が容易
- 設定ファイルでモデル切り替え可能
- 送信先デバイスの動的追加

---

## 7. 制約事項

### 技術的制約
- M5Stack LLM Compute Kitでのみ動作
- StackFlow APIに依存
- オフライン動作（翻訳モデルがインストール済みの場合）

### 機能的制約
- LLM出力は最大64トークン
- TTS音声はリアルタイム再生のみ（ファイル保存なし）
- OSCプロトコルのみ対応

---

## 8. 参考資料

- M5Stack LLM Compute Kit ドキュメント
- StackFlow API仕様書
- OSC 1.0 プロトコル仕様
- MeloTTS モデルドキュメント
