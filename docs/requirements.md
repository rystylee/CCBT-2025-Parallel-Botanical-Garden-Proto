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

### 2.1 デバイスの役割

全てのBIデバイスは同一の動作を行います：
- 他のBIデバイスからの信号を受け付ける
- 人間の声（マイク入力）を受け付ける
- 入力: `{relay_count, text}`
  - `relay_count`: メッセージの伝達回数（0から始まる整数）
  - `text`: テキスト内容

**注意**: どのBIデバイスにも人間の入力を送ることができます。

### 2.2 動作サイクル

各BIデバイスは独立した4段階のサイクルで動作：

```
1. 入力受付期間（3秒）
   ↓ OSC経由で入力データを受け付け（複数可）
   ↓ 受信時に伝達回数が上限を超えるデータは即座に破棄

2. 生成期間
   ↓ 入力データを受信順に連結
   ↓ LLMで続きのテキストを生成（2~3トークン）

3. 出力期間
   ↓ バッファが空の場合はスキップ
   ↓ LEDフェードアップ（0.0→1.0）
   ↓ 全入力+生成をTTS音声生成・再生
   ↓ LEDフェードダウン（1.0→0.0）
   ↓ 生成テキストをOSC送信（次のBIへ）

4. 休息期間（1秒）
   ↓ 待機

→ サイクル1に戻る
```

### 2.3 伝達回数管理仕様

**伝達回数のカウントと伝播**

1. **伝達回数の初期値**
   - **人間からの入力時**、`relay_count=0`で開始
   - BIデバイスが受信したデータには既に伝達回数が含まれている

2. **伝達回数のインクリメント**
   - データ受信時（`add_input()`呼び出し時）に受信した`relay_count`に1を加算
   - 加算後の値をバッファに保存
   - BIが他のBIに信号を送る際は、**加算後の`relay_count`を使用**

3. **伝達回数の上限チェック**
   - データ受信時（`add_input()`呼び出し時）に即座にチェック
   - 受信した`relay_count`が`max_relay_count`（デフォルト6）以上の場合、そのデータを破棄
   - フィルタリングは受信の都度実行される

4. **複数入力時の処理**
   - バッファ内に複数の入力がある場合、**最も小さい（最小値の）`relay_count`**を次のBIへ送信

**データフロー例**

```
[人間] --relay:0--> [BI-A] --relay:1--> [BI-B] --relay:2--> [BI-C] --relay:3--> ...
  ↑                   ↑                   ↑                   ↑
新規発行            +1して転送          +1して転送          +1して転送
```

**複数入力時の処理例**

```
[BI-A のバッファ]
- Input A (relay_count: 2, text: "こんにちは")  ← 最小
- Input B (relay_count: 3, text: "今日は")

→ 連結テキスト: "こんにちは今日は晴れです" (LLMで「晴れです」を生成)
→ 次のBIへ送信: relay_count=2, text="晴れです"  ← 最小の伝達回数を使用
```

**理由**: 最小の伝達回数を使用することで、データの寿命を最大化し、ネットワーク全体でデータが長く循環できるようにする

---

## 3. 主要機能

### 3.1 LLM推論
- **モデル**: qwen2.5-0.5B-prefill-20e
- **出力**: 最大128トークン（通常2~3トークン）
- **プロンプト**: 詩的な短文生成に特化
- **Soft Prefix**: bf16形式のプリフィックスチューニング対応

### 3.2 TTS音声合成
- **モデル**: MeloTTS (日本語/英語/中国語)
- **出力方式**: WAVファイル書き出し→tinyplay再生 (v2.1以降)
- **API**: OpenAI互換API (`http://127.0.0.1:8000/v1`)
- **フォーマット**: WAV形式（16kHz, mono, s16）
- **後処理**: FFmpeg変換（オプション）、ランブルエフェクト（オプション）
- **音量**: デフォルト15%
- **LED連動**: TTS再生開始前にLEDフェードアップ、再生終了後にLEDフェードダウン

### 3.3 OSC通信

#### 受信エンドポイント（UDP: 8000）
| エンドポイント | 引数 | 機能 |
|------------|------|------|
| `/bi/input` | relay_count, text | 入力データ受付 |
| `/bi/stop` | なし | サイクル停止 |
| `/bi/status` | なし | ステータス取得 |

**注意**: サイクルはアプリケーション起動時に自動開始されます。

#### 送信
- **BIデバイス間通信**: `/bi/input` 経由で次のBIデバイスへ生成テキストを送信
  - 送信先: 設定ファイル（networks.csv）で指定
  - 送信内容: `relay_count, generated_text`
- **Mixer PC送信**: `/mixer` 経由で生成テキストを送信
  - 送信先: config.json の `mixer` セクションで指定
  - 送信内容: `generated_text` のみ
  - 送信タイミング: LLM生成成功時に毎回送信
- **LED制御**: `/led` 経由でLED輝度を制御
  - 送信先: config.json の `led_control.targets` で指定
  - 送信内容: `value` (0.0-1.0の輝度値)
  - 送信タイミング: TTS開始前（フェードアップ）、TTS終了後（フェードダウン）

---

## 4. 設定ファイル構造

### 4.1 config/config.json

デバイス固有の設定を記述：

```json
{
  "network": {
    "device_id": 1,                    // 自分のデバイスID
    "csv_path": "config/networks.csv"  // ネットワーク設定CSVのパス
  },
  "cycle": {
    "receive_duration": 3.0,  // 入力受付期間（秒）
    "rest_duration": 1.0,     // 休息期間（秒）
    "max_relay_count": 6      // 伝達回数の上限（これ以上は破棄）
  },
  "osc": {
    "receive_port": 8000
  },
  "mixer": {
    "host": "10.0.0.200",    // Mixer PCのIPアドレス
    "port": 8000             // Mixer PCのOSCポート
  },
  "common": {
    "lang": "ja"  // "en", "zh", "fr"
  },
  "stack_flow_llm": {
    "max_tokens": 128
  },
  "led_control": {
    "enabled": true,              // LED制御の有効/無効
    "targets": [                  // LED制御の送信先
      {
        "host": "127.0.0.1",      // 通常は自分のマシン（pca9685_osc_led_server.py）
        "port": 9000
      }
    ],
    "fade_steps": 40,             // フェードのステップ数
    "fade_up_duration": 2.0,      // フェードアップの時間（秒）
    "fade_down_duration": 2.0     // フェードダウンの時間（秒）
  }
}
```

### 4.2 config/networks.csv

全デバイスのネットワーク情報を一元管理：

```csv
ID,IP,To
1,10.0.0.1,"2,5"
2,10.0.0.2,"3,6"
3,10.0.0.3,"4,7"
...
```

- **ID**: デバイスID
- **IP**: デバイスのIPアドレス（ルール: ID X → 10.0.0.X）
- **To**: 送信先デバイスIDのカンマ区切りリスト

**設定の仕組み**:
1. config.jsonで自分のdevice_idを指定
2. 起動時にnetworks.csvから該当IDの情報を読み込み
3. IPアドレスと送信先が自動的に解決される

### 4.3 音声出力設定（v2.1以降）

config.jsonに音声出力関連の設定を追加：

```json
"audio": {
  "tinyplay_card": 0,              // ALSAカード番号
  "tinyplay_device": 1,            // ALSAデバイス番号
  "sample_rate": 16000,            // サンプリングレート（Hz）
  "channels": 1,                   // チャンネル数（1: mono, 2: stereo）
  "sample_format": "s16",          // サンプルフォーマット（s16, s32, etc.）
  "enable_ffmpeg_convert": true,   // FFmpeg変換の有効/無効
  "enable_rumble_effect": false,   // ランブルエフェクトの有効/無効
  "temp_wav_dir": "./tmp",         // 一時ファイル保存先

  // 高度なランブルエフェクト設定（v2.2以降）
  "rumble_pitch_steps": -16.0,     // ピッチシフト（半音単位、-16 ≈ -1.3オクターブ）
  "rumble_sub_oct_mix": 0.55,      // サブオクターブレイヤーのミックス量（0..1）
  "rumble_mix": 0.25,              // シンセティックランブルノイズのミックス量（0..1）
  "rumble_base_hz": 55.0,          // ランブル生成のベース周波数（Hz）
  "rumble_drive": 0.55,            // ディストーションドライブ量（0..1）
  "rumble_xover_hz": 280.0         // クロスオーバー周波数（Hz）
}
```

---

## 5. 依存関係

### Pythonライブラリ
- loguru (ロギング)
- python-osc (OSCプロトコル)
- openai (OpenAI互換TTS API)
- numpy (数値演算、信号処理)
- scipy (科学計算、フィルタリング)
- soundfile (音声ファイルI/O)
- argostranslate (オフライン翻訳) ※現在未使用、将来的なオプション機能として保持
- googletrans (Google翻訳API) ※現在未使用、将来的なオプション機能として保持

### StackFlowモデル
- llm-model-qwen2.5-0.5B-prefill-20e
- llm-model-melotts-ja-jp
- llm-model-melotts-en-us
- llm-model-melotts-zh-cn

### システムコマンド（v2.1以降）
- FFmpeg: WAV音声ファイルの変換（サンプリングレート、チャンネル数、フォーマット変換）
- tinyplay: ALSA経由での音声ファイル再生

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
- FFmpeg、tinyplayコマンドが必要（v2.1以降）

### 機能的制約
- LLM出力は最大64トークン
- TTS音声はWAVファイル経由で再生（v2.1以降、ファイル保存可能）
- OSCプロトコルのみ対応
