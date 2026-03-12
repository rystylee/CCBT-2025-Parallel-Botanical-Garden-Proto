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
- 入力: `{text, soft_prefix_b64, relay_count}`
  - `text`: テキスト内容
  - `soft_prefix_b64`: LLM推論用のsoft prefix（Base64エンコード済みbf16データ）
  - `relay_count`: メッセージの伝達回数（0から始まる整数）

**注意**: どのBIデバイスにも人間の入力を送ることができます。

### 2.2 動作サイクル

各BIデバイスは独立した4段階のサイクルで動作：

```
1. 入力受付期間（3秒）
   ↓ OSC経由で入力データを受け付け（複数可）
   ↓ 受信時に伝達回数が上限を超えるデータは即座に破棄

2. 生成期間
   ↓ 入力データを受信順に連結
   ↓ 入力データのsoft_prefix_b64を使用してLLMで続きのテキストを生成（2~3トークン）

3. 出力期間
   ↓ バッファが空の場合はスキップ
   ↓ LEDフェードアップ（0.0→1.0）
   ↓ 全入力+生成をTTS音声生成・再生
   ↓ LEDフェードダウン（1.0→0.0）
   ↓ 生成テキストとsoft_prefix_b64をOSC送信（次のBIへ）

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
- **モデル**: TinySwallow-1.5B（全言語共通）
- **出力**: 最大64トークン（通常2~3トークン）
- **プロンプト**: 詩的な短文生成に特化（言語別システムプロンプト）
- **Soft Prefix**: bf16形式のプリフィックスチューニング対応
- **Soft Prefix値**: config.jsonの`stack_flow_llm.soft_prefix_vals`からランダム選択
- **最大出力文字数**: 言語別に制限（ja: 20文字、en/fr: 50文字、fa/ar: 40文字）
- **NGワードフィルタリング**: 生成テキストから不適切な単語を自動除去（`config/ngwords.json`）

### 3.2 TTS音声合成
- **モデル**: MeloTTS (日本語/英語/中国語/フランス語/ペルシャ語/アラビア語)
- **出力方式**: WAVファイル書き出し→FFmpegエフェクト処理→aplay/tinyplay再生
- **API**: OpenAI互換API (`http://127.0.0.1:8000/v1`)
- **フォーマット**: WAV形式（48kHz, stereo, s16）
- **テキスト前処理**: ひらがな化＋母音伸ばしエフェクト（日本語のみ、オプション）
- **音響エフェクト**: "Accumulating Ghosts"パイプライン（デフォルト、詳細は3.3節）
- **ピッチシフト**: 倍音列ベースの音程からランダム選択（オプション）
- **速度変更**: atempo（タイムストレッチ）またはtape（テープ速度）モード（オプション）
- **再生デバイス**: ALSA dmixer経由
- **LED連動**: TTS再生中はLEDフェード制御（RECEIVING/GENERATING状態別）
- **待機音声**: RECEIVING/GENERATING中に待機音声をランダムループ再生（`audio/AE_*.wav`など）

### 3.3 音響エフェクト処理（Accumulating Ghosts Pipeline）

TTS生成音声に対し、Jóhann Jóhannsson風の「蓄積するゴースト」音響処理を適用：

**パイプライン構成**:
```
TTS生WAV → セグメント分割 → ゴースト蓄積 → ギャップフィル → ミックス
  → サチュレーション → Schroederリバーブ → マルチバンドEQ
  → コンプレッサー → ステレオ化 → ピッチシフト → 速度変更
```

**主要コンポーネント**:

1. **セグメンテーション**: エネルギーベースで音節単位に分割
2. **ゴースト蓄積**: 各音節がスペクトル残像（ゴースト）を残す。後半ほどローパスカットオフが下がり暗い倍音クラスターに
3. **ギャップフィル**: 音節間の無音区間をスペクトルモーフで補間
4. **Schroederリバーブ**: 全帰還コムフィルタ+オールパスによるアルゴリズミックリバーブ
5. **マスタリング**: テープサチュレーション→マルチバンドEQ→コンプレッサー
6. **ステレオ化**: Haas式デコリレーション（左右微小遅延差）

**設定項目** (`config.json`の`audio`セクション):
- `effect_mode`: "ghost"（ゴーストパイプライン）、"rumble"（旧ランブルエフェクト）、"off"（エフェクトなし）
- `ghost`: ゴースト蓄積パラメータ（linger_s、level、cutoff_start、cutoff_decay、resonance、freeze_mode）
- `segmentation`: セグメント分割パラメータ（silence_threshold、min_segment_ms、max_segment_ms）
- `bloom`: セグメントフェード（attack_ms、release_ms）
- `gap_fill`: ギャップフィルパラメータ（level、cutoff）
- `reverb`: リバーブパラメータ（room_size、damping、wet、predelay_ms）
- `mastering`: マスタリングパラメータ（saturation_drive、low_boost_db、mid_cut_db、air_boost_db、comp_threshold_db、comp_ratio）
- `stereo_width`: ステレオ幅（0-1）
- `global_bloom`: 全体フェード（attack_s、release_s）
- `voice_level`: ミックス内での声の音量バランス

**詳細**: 実装は[api/audio_effects.py](../api/audio_effects.py)を参照

### 3.4 テキスト変換（日本語のみ）

TTS入力テキストに対し、以下の変換を適用（オプション）：

1. **ひらがな化**: カタカナ→ひらがな変換（pykakasi使用、未インストール時は単純置換）
2. **母音伸ばし**: 各文字を確率的に伸ばす
   - `elongation_mode`: "dash"（長音符「ー」）、"vowel"（母音繰返し「ああ」）、"mixed"（ランダム混合）、"off"（伸ばしなし）
   - `elongation_probability`: 各文字が伸ばされる確率（0-1）
   - `elongation_length`: 伸ばす長さの範囲（min-max文字数）

**設定項目** (`config.json`の`audio.text_transform`):
```json
"text_transform": {
  "enabled": true,
  "to_hiragana": true,
  "elongation_mode": "mixed",
  "elongation_probability": 0.8,
  "elongation_length": {"min": 2, "max": 5}
}
```

**詳細**: 実装は[api/text_transform.py](../api/text_transform.py)を参照

### 3.5 LED制御

**PCA9685 OSC LED Server** (`pca9685_osc_led_server.py`):
- I2C経由でPCA9685 PWMドライバを制御
- OSC経由で輝度制御を受け付け
- サイクル状態に応じた輝度範囲の設定
- フェードアップ/ダウンアニメーション
- Soft Prefix更新イベント時の特別なLEDパフォーマンス

**設定項目** (`config.json`の`led_control`):
- `enabled`: LED制御の有効/無効
- `targets`: LED制御OSCの送信先リスト
- `fade_steps`: フェードのステップ数
- `fade_up_duration` / `fade_down_duration`: フェードの時間（秒）
- `receiving_min_brightness` / `receiving_max_brightness`: RECEIVING状態の輝度範囲
- `generating_min_brightness` / `generating_max_brightness`: GENERATING状態の輝度範囲
- `soft_prefix.default_fade_up_duration` / `default_fade_down_duration`: Soft Prefix更新時のフェード時間
- `pca9685`: PCA9685ハードウェア設定（I2Cアドレス、チャンネル、バス、周波数、ガンマ補正など）

**詳細**: [pca9685_osc_led_server.py](../pca9685_osc_led_server.py)を参照

### 3.6 植物センサー統合

**植物センサーデータの自動取得とSoft Prefix制御**:

- **クロロフィル蛍光（CF）デバイス**: クロロフィル蛍光値の測定
- **Acoustic Emission（AE）センサー**: 植物の音響放射の測定
- **AE×CFマトリクス**: 2次元マトリクスでsoft_prefix値を動的に決定
- **自動OSC送信**: `/bi/soft_prefix_update`エンドポイント経由でBIシステムに通知

**設定ファイル**: `config/plant_sensor_config.json`

**詳細**: [docs/plant_sensor.md](plant_sensor.md)を参照（別途作成予定）

### 3.7 入力制御（Input Controller）

**音声入力とセンサー入力の統合システム**:

- **STT（Speech-to-Text）**: OpenAI Whisper APIを使用した音声認識
- **センサー入力**: シリアル通信経由でセンサーデータを受信
- **BiInputSender**: 入力データをOSC経由でBIシステムに送信

**設定ファイル**: `input_controller/input_config.example.json`

**詳細**: [docs/input_controller.md](input_controller.md)を参照（別途作成予定）

### 3.8 デバイスID・言語の自動検出

**デバイスID自動検出**:
1. `/etc/ccbt-device-id`ファイルから読み込み（優先）
2. `/etc/network/interfaces`の最後の行から抽出（フォールバック）

**言語自動検出**:
- デバイスIDの末尾の数字から言語を自動決定
  - 1-2: `ja`（日本語）
  - 3-4: `en`（英語）
  - 5-6: `fr`（フランス語）
  - 7-8: `fa`（ペルシャ語）
  - 9-0: `ar`（アラビア語）

**詳細**: [main.py:resolve_device_id()](../main.py)、[main.py:resolve_lang_from_device_id()](../main.py)を参照

### 3.9 OSC通信

#### 受信エンドポイント（UDP: 8000）
| エンドポイント | 引数 | 機能 |
|------------|------|------|
| `/bi/input` | text, soft_prefix_b64, relay_count | 入力データ受付 |
| `/bi/soft_prefix_update` | soft_prefix_val, cf_value, ae_value | Soft Prefix更新＋LED パフォーマンス |
| `/bi/stop` | なし | サイクル停止 |
| `/bi/status` | なし | ステータス取得 |

**注意**: サイクルはアプリケーション起動時に自動開始されます。

#### 送信
- **BIデバイス間通信**: `/bi/input` 経由で次のBIデバイスへ生成テキストを送信
  - 送信先: 設定ファイル（networks.csv）で指定
  - 送信内容: `generated_text, soft_prefix_b64, relay_count`
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

### 4.3 音声出力設定

config.jsonの`audio`セクションで音声出力関連の設定を管理：

**基本設定**:
```json
"audio": {
  "playback_device": "dmixer",         // 再生デバイス（dmixer、tinyplay、aplay）
  "tinyplay_card": 0,                  // ALSAカード番号
  "tinyplay_device": 1,                // ALSAデバイス番号
  "sample_rate": 48000,                // サンプリングレート（Hz）
  "channels": 2,                       // チャンネル数（1: mono, 2: stereo）
  "sample_format": "s16",              // サンプルフォーマット（s16, s32）
  "enable_ffmpeg_convert": true,       // FFmpeg変換の有効/無効
  "enable_rumble_effect": true,        // エフェクト処理の有効/無効（ghostまたはrumble）
  "temp_wav_dir": "./tmp",             // 一時ファイル保存先

  // 待機音声ループ
  "waiting_audio_dir": "audio",        // 待機音ファイルディレクトリ
  "waiting_audio_prefix": "AE_",       // 待機音ファイルのプレフィックス

  // エフェクトモード
  "effect_mode": "ghost",              // ghost（ゴーストパイプライン）、rumble（旧ランブル）、off（エフェクトなし）

  // ピッチシフト
  "pitch_shift": {
    "enabled": true,
    "semitones": [-3, -2, 0, 0, 2, 3]  // 半音単位のピッチ候補リスト
  },

  // 速度変更
  "speed": {
    "mode": "atempo",                  // atempo（タイムストレッチ）、tape（テープ速度）、off
    "value": 0.8,                      // 固定速度倍率（nullでランダム）
    "range": {"min": 0.5, "max": 1.3}  // ランダム時の範囲
  },

  // テキスト変換（日本語のみ）
  "text_transform": {
    "enabled": true,
    "to_hiragana": true,               // カタカナ→ひらがな変換
    "elongation_mode": "mixed",        // dash、vowel、mixed、off
    "elongation_probability": 0.8,     // 伸ばす確率（0-1）
    "elongation_length": {"min": 2, "max": 5}  // 伸ばす長さ範囲
  },

  // ゴーストエフェクト設定（詳細はconfig.jsonを参照）
  "ghost": { ... },
  "segmentation": { ... },
  "bloom": { ... },
  "gap_fill": { ... },
  "reverb": { ... },
  "mastering": { ... },
  "stereo_width": 0.25,
  "global_bloom": { ... },
  "voice_level": 0.56
}
```

**詳細な設定項目**: 実際の[config/config.json](../config/config.json)を参照（全パラメータに詳細なコメント付き）

### 4.4 LED制御設定

config.jsonの`led_control`セクションでLED制御の設定を管理：

```json
"led_control": {
  "enabled": true,
  "targets": [
    {"host": "127.0.0.1", "port": 9000}
  ],
  "fade_steps": 40,
  "fade_up_duration": 15.0,              // TTS開始時のフェードアップ時間（秒）
  "fade_down_duration": 15.0,            // TTS終了時のフェードダウン時間（秒）
  "receiving_min_brightness": 0.0,       // RECEIVING状態の最小輝度
  "receiving_max_brightness": 0.1,       // RECEIVING状態の最大輝度
  "generating_min_brightness": 0.05,     // GENERATING状態の最小輝度
  "generating_max_brightness": 0.25,     // GENERATING状態の最大輝度
  "soft_prefix": {
    "default_fade_up_duration": 2.0,
    "default_fade_down_duration": 2.0
  },
  "pca9685": {
    "addr": 64,                          // I2Cアドレス
    "channel": 0,                        // PWMチャンネル
    "bus": null,                         // I2Cバス番号（nullで自動）
    "freq": 1000.0,                      // PWM周波数（Hz）
    "gamma": 1.0,                        // ガンマ補正
    "max_brightness": 1.0,               // 最大輝度
    "fade": 0.0,                         // フェード時間
    "rate": 100.0,                       // 更新レート（Hz）
    "reconnect_interval": 2.0            // 再接続間隔（秒）
  }
}
```

### 4.5 LLM設定（言語別）

config.jsonの`llm_settings`セクションで言語別のLLM設定を管理：

```json
"llm_settings": {
  "ja": {
    "model": "TinySwallow-1.5B",
    "system_prompt": "植物の翻訳者。森林の詩を短い単語で紡ぐ。",
    "instruction_prompt": "続き: "
  },
  "en": {
    "model": "TinySwallow-1.5B",
    "system_prompt": "Translator of plants. String short words about forests.",
    "instruction_prompt": "continue: "
  },
  // fr、fa、ar、zhも同様
}
```

---

## 5. 依存関係

### Pythonライブラリ
- **loguru**: ロギング
- **python-osc**: OSCプロトコル
- **openai**: OpenAI互換TTS/STT API
- **numpy**: 数値演算、信号処理
- **scipy**: 科学計算、フィルタリング、音響エフェクト
- **soundfile**: 音声ファイルI/O
- **smbus2**: I2C通信（PCA9685制御用）
- **pykakasi**: ひらがな変換（オプション、未インストール時は単純置換）
- **flask**: Web管理UI（Monitor用）
- **flask-socketio**: リアルタイム通信（Monitor用）
- **paramiko**: SSH接続（Monitor用）
- **pyserial**: シリアル通信（Input Controller用）

### StackFlowモデル
- **llm-model-TinySwallow-1.5B**: LLM推論（全言語共通）
- **llm-model-melotts-ja-jp**: 日本語TTS
- **llm-model-melotts-en-us**: 英語TTS
- **llm-model-melotts-zh-cn**: 中国語TTS
- **llm-model-melotts-fr-fr**: フランス語TTS
- **llm-model-melotts-fa-ir**: ペルシャ語TTS
- **llm-model-melotts-ar-sa**: アラビア語TTS

### システムコマンド
- **FFmpeg**: 音声エフェクト処理、フォーマット変換、ピッチシフト、速度変更
- **aplay** / **tinyplay**: ALSA経由での音声ファイル再生
- **i2cdetect**: I2Cデバイス検出（PCA9685用）

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
- M5Stack LLM Compute Kitでのみ動作（x86_64/ARM64 Ubuntu環境）
- StackFlow APIに依存
- オフライン動作可能（全モデルがインストール済みの場合）
- FFmpeg、aplay/tinyplayコマンドが必要
- PCA9685 LED制御にはI2Cバスとsmbus2ライブラリが必要
- ひらがな変換にはpykakasiが必要（オプション）

### 機能的制約
- LLM出力は最大64トークン
- TTS音声はWAVファイル経由で再生（一時ファイルを`./tmp`に保存）
- OSCプロトコルのみ対応
- テキスト変換（ひらがな化、母音伸ばし）は日本語のみ対応

### 運用上の制約
- 長時間動作を想定（systemd自動起動推奨）
- 植物センサー統合は別プロセス（`config/plant_sensor_config.json`で設定）
- Input Controllerは別プロセス（`input_controller/`で管理）
- Monitor（Web管理UI）は別プロセス（`monitor/`で管理）

---

## 8. 関連ドキュメント

- **実装計画**: [docs/plan.md](plan.md)
- **タスクリスト**: [docs/tasks.md](tasks.md)
- **植物センサー統合**: [docs/plant_sensor.md](plant_sensor.md)（作成予定）
- **Input Controller**: [docs/input_controller.md](input_controller.md)（作成予定）
- **Monitor**: [docs/monitor.md](monitor.md)（作成予定）
- **デプロイ手順**: [docs/deployment.md](deployment.md)（作成予定）
- **開発者向けガイド**: [docs/development.md](development.md)（作成予定）

---

## 9. 開発者向け情報

### デバッグモード
- **Raw Audio Debug**: `--raw-audio`フラグでFFmpeg処理をスキップし、生のWAVを保存してaplayで再生

### ログ
- loguruによる詳細ログ出力
- ログレベル: DEBUG、INFO、WARNING、ERROR

### テストスクリプト
- `tools/`ディレクトリに各種テストスクリプトあり
