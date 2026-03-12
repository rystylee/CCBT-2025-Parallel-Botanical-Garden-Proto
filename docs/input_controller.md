# Input Controller

Input Controllerは、音声入力（STT）とセンサー入力を統合し、BIデバイスにOSC経由でデータを送信するシステムです。通常、Ubuntu PC（10.0.0.200）上で動作し、複数のマイクチャンネルとセンサー入力を並行処理します。

---

## 概要

### 主な機能

- **多チャンネル音声入力**: 最大4チャンネルの同時音声認識
- **OpenAI Whisper STT**: ローカルWhisperモデルによる高精度音声認識
- **センサー入力**: シリアル通信またはOSC経由でセンサーデータを受信
- **Soft Prefix生成**: 音声・センサーデータから自動的にSoft Prefixを生成
- **マルチターゲット送信**: チャンネル/センサー別に複数のBIデバイスへ送信
- **非同期処理**: asyncio による高効率な並行処理

### システム構成

```
[Ubuntu PC: 10.0.0.200]
├── マイク入力（4ch）
│   ├── ch0 → Whisper STT → BI Device 1-10
│   ├── ch1 → Whisper STT → BI Device 11-20
│   ├── ch2 → Whisper STT → BI Device 21-30
│   └── ch3 → Whisper STT → BI Device 31-40
│
└── センサー入力
    ├── シリアル → 値読取 → BI Device 41-50
    └── OSC → 値受信 → BI Device 51-60
```

---

## ファイル構成

```
input_controller/
├── __main__.py                    # エントリーポイント
├── main.py                        # InputController メインロジック
├── config.py                      # 設定管理
├── stt.py                         # Speech-to-Text（Whisper）
├── mic.py                         # マイク入力
├── speaker.py                     # スピーカー出力（オプション）
├── sensor_receiver.py             # センサーデータ受信（OSC）
├── soft_prefix.py                 # Soft Prefix生成
├── sender.py                      # BiInputSender（OSC送信）
├── audio_backend.py               # オーディオバックエンド抽象化
├── plant_sensor_processor.py      # 植物センサー処理
├── check_audio.py                 # オーディオデバイス確認ツール
├── test_sensor_input.py           # センサー入力テスト
└── input_config.example.json      # 設定ファイル例
```

---

## インストール

### 前提条件

- Ubuntu PC（推奨: 10.0.0.200）
- Python 3.10以上
- マイクデバイス（USBオーディオインターフェースなど）
- OpenAI Whisperモデル（自動ダウンロード）

### 依存関係

```bash
# 主要なPythonパッケージ
pip install openai-whisper sounddevice numpy scipy python-osc pyserial
```

---

## 設定ファイル

### input_config.example.json

設定ファイルの例：

```json
{
  "input_controller": {
    "self_ip": "10.0.0.200",           // 自分のIPアドレス
    "osc_receive_port": 9001,          // OSC受信ポート（センサー用）
    "audio_backend": "sounddevice",    // オーディオバックエンド
    "audio_device": "",                // オーディオデバイス名（空文字でデフォルト）
    "mic_channels": 4,                 // マイクチャンネル数
    "mic_sample_rate": 16000,          // サンプリングレート（Hz）
    "mic_record_sec": 8.0,             // 録音時間（秒）
    "mic_interval_sec": 2.0,           // 録音間隔（秒）
    "mic_silence_threshold": 0.01,     // 無音判定閾値
    "stt_model": "base",               // Whisperモデル（tiny/base/small/medium/large）
    "stt_language": "ja",              // STT言語（ja/en/fr など）
    "stt_device": "cpu",               // デバイス（cpu/cuda）
    "stt_max_workers": 4,              // 並列処理ワーカー数
    "speaker_enabled": true,           // スピーカー出力の有効/無効
    "speaker_wav_dir": "./output_wav", // WAV保存先
    "speaker_player": "aplay",         // 再生コマンド
    "speaker_player_args": [],         // 再生コマンド引数
    "soft_prefix_p": 1,                // Soft Prefix P次元
    "soft_prefix_h": 1536,             // Soft Prefix H次元

    // マイクチャンネル別ルール
    "mic_rules": [
      {
        "channel": 0,                  // マイクチャンネル番号
        "target_ids": [1, 2, 3, ...],  // 送信先BIデバイスID
        "min_text_len": 2,             // 最小テキスト長（これ以下は送信しない）
        "port": 8000                   // 送信先ポート
      }
      // ch1, ch2, ch3 も同様
    ],

    // センサー入力ルール
    "sensor_rules": [
      {
        "osc_address": "/sensor/plant", // OSCアドレス
        "target_ids": [41, 42, ...],    // 送信先BIデバイスID
        "data_key": "plant",            // データキー
        "port": 8000                    // 送信先ポート
      }
    ]
  }
}
```

### 設定項目の詳細

#### 音声入力設定

- **mic_channels**: マイクチャンネル数（1-8）
- **mic_sample_rate**: サンプリングレート（Whisperは16kHzを推奨）
- **mic_record_sec**: 1回の録音時間（長すぎると応答性が低下）
- **mic_interval_sec**: 録音間隔（短いと負荷が高い）
- **mic_silence_threshold**: 無音判定閾値（0.01-0.05が一般的）

#### STT設定

- **stt_model**: Whisperモデルサイズ
  - `tiny`: 最速、精度低め（39M）
  - `base`: 高速、精度良好（74M） **← 推奨**
  - `small`: やや遅い、精度高め（244M）
  - `medium`: 遅い、精度高い（769M）
  - `large`: 最遅、最高精度（1550M）
- **stt_language**: 言語コード（ja/en/fr/zh/ko など）
- **stt_device**: 推論デバイス（cpu/cuda）

#### Soft Prefix設定

- **soft_prefix_p**: P次元（通常1）
- **soft_prefix_h**: H次元（モデルの隠れ層サイズ、TinySwallow-1.5Bは1536）

#### マイクルール

各マイクチャンネルごとに：
- 送信先BIデバイスIDのリスト
- 最小テキスト長（短すぎるノイズを除外）
- 送信先ポート（通常8000）

#### センサールール

各センサー入力ごとに：
- OSCアドレス（受信するOSCエンドポイント）
- 送信先BIデバイスIDのリスト
- データキー（OSCメッセージ内のキー）
- 送信先ポート

---

## 起動方法

### 通常起動

```bash
cd input_controller
python -m input_controller --config input_config.json
```

### ダミーセンサーモード（センサーなしでテスト）

```bash
python -m input_controller --config input_config.json --dummy-sensor
```

### オーディオデバイスの確認

```bash
python check_audio.py
```

出力例：
```
Available audio devices:
  0: HDA Intel PCH: ALC887-VD Analog (hw:0,0)
  1: USB Audio Device: Audio (hw:1,0)  <- 使用するデバイス
  ...
```

---

## 動作フロー

### 音声入力パイプライン

```
1. マイク録音（8秒間、16kHz）
   ↓
2. Whisper STT（非同期処理）
   ↓
3. テキスト長チェック（min_text_len）
   ↓ OK
4. Soft Prefix生成（ランダム値、bf16形式）
   ↓
5. OSC送信（/bi/input）
   - text: 認識テキスト
   - soft_prefix_b64: Base64エンコード済みSoft Prefix
   - relay_count: 0（新規入力）
   ↓
6. 送信先BIデバイス（target_ids）
   ↓
7. 待機（mic_interval_sec）
   ↓
8. 1に戻る
```

### センサー入力パイプライン

```
1. OSC受信（/sensor/plant など）
   ↓
2. センサー値取得（float）
   ↓
3. Soft Prefix生成（値ベース、bf16形式）
   ↓
4. OSC送信（/bi/input）
   - text: "[sensor:0.123]"
   - soft_prefix_b64: センサー値から生成
   - relay_count: 0
   ↓
5. 送信先BIデバイス（target_ids）
   ↓
6. 待機
   ↓
7. 1に戻る
```

---

## Soft Prefix生成

### 音声入力の場合

ランダムにSoft Prefix値を選択：

```python
VALS = [0.0, 1e-4, 1e-3, 1e-2]
val = random.choice(VALS)  # ランダム選択
u16 = f32_to_bf16_u16(val)  # bf16に変換
raw = struct.pack("<H", u16) * (p * h)  # P×H 次元の配列
soft_prefix_b64 = base64.b64encode(raw).decode("ascii")
```

### センサー入力の場合

センサー値を直接使用：

```python
val = sensor_value  # 例: 0.123
u16 = f32_to_bf16_u16(val)
raw = struct.pack("<H", u16) * (p * h)
soft_prefix_b64 = base64.b64encode(raw).decode("ascii")
```

---

## トラブルシューティング

### マイクが認識されない

```bash
# オーディオデバイスを確認
python check_audio.py

# デバイス名を設定ファイルに指定
"audio_device": "USB Audio Device"
```

### STTが遅い

```bash
# より小さいモデルを使用
"stt_model": "tiny"  # または "base"

# GPUを使用（CUDA対応の場合）
"stt_device": "cuda"
```

### センサーデータが受信できない

```bash
# センサー入力をテスト
python test_sensor_input.py

# OSC受信ポートを確認
"osc_receive_port": 9001
```

### 送信先BIデバイスに届かない

```bash
# ネットワーク疎通確認
ping 10.0.0.1  # BIデバイスのIP

# OSC送信をテスト（別のマシンから）
python scripts/send_bi_input.py -H 10.0.0.1 -t "test"
```

---

## 開発者向け情報

### 主要クラス

#### InputController (main.py)

```python
class InputController:
    def __init__(self, config: InputControllerConfig, use_dummy=False):
        # STT、センサー、送信クライアントを初期化

    async def start(self):
        # 音声ループ、センサーループを並行起動

    async def _voice_loop(self, rule, lid=0):
        # マイク録音 → STT → 送信

    async def _sensor_loop(self, rule, sensor, lid=0):
        # センサー読取 → 送信
```

#### SpeechToText (stt.py)

```python
class SpeechToText:
    def __init__(self, model_size="base", language="ja", device="cpu"):
        # Whisperモデルをロード

    async def record_and_transcribe(self) -> str:
        # 録音 → 文字起こし
```

#### BiInputSender (sender.py)

```python
class BiInputSender:
    def send_to_targets(self, targets, text, soft_prefix_b64, relay_count):
        # 複数のBIデバイスに /bi/input を送信
```

### テストスクリプト

```bash
# オーディオデバイステスト
python check_audio.py

# センサー入力テスト
python test_sensor_input.py

# ダミーモードでの動作確認
python -m input_controller --config input_config.json --dummy-sensor
```

---

## 関連ドキュメント

- **メインシステム**: [docs/requirements.md](requirements.md)
- **植物センサー統合**: [docs/plant_sensor.md](plant_sensor.md)
- **ネットワーク設定**: [config/networks.csv](../config/networks.csv)
