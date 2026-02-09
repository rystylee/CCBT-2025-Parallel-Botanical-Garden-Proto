# 実装計画書

## 1. プロジェクト実装概要

### 1.1 開発ステータス
- **現在のバージョン**: v2.0（分散BIシステム）
- **実装状況**: コア機能実装完了、テスト・最適化フェーズ

### 1.2 v2.0の主要機能
- サイクル駆動型の動作モデル
- 分散複数デバイス対応
- バッファリング＋時系列連結処理
- 短文生成（2~3トークン）
- タイムスタンプ管理

---

## 2. アーキテクチャ設計

### 2.1 モジュール構成

```
CCBT-2025-Parallel-Botanical-Garden-Proto/
├── main.py                    # エントリーポイント
├── bi/                        # BI関連モジュール
│   ├── __init__.py
│   ├── controller.py         # BIController クラス
│   ├── models.py             # BIInputData データクラス
│   └── utils.py              # Soft Prefix生成ユーティリティ
├── app/                       # アプリケーション層
│   ├── __init__.py
│   └── controller.py         # AppController クラス
├── api/                       # API層
│   ├── llm.py                # LLMクライアント
│   ├── tts.py                # TTSクライアント
│   ├── osc.py                # OSCサーバー/クライアント
│   └── utils.py              # LLM/TTS設定
├── stackflow/                 # StackFlow通信
│   └── utils.py
├── config/                    # 設定ファイル
│   └── config.json
└── tests/                     # テストスクリプト
    ├── test_bi.py
    └── test_multi_target.py
```

### 2.2 BIController 状態機械

```
     ┌────────────┐
     │  RECEIVING │ (3秒)
     │  ・入力受付 │
     │  ・フィルタ │
     └──────┬─────┘
            ↓
     ┌─────────────┐
     │ GENERATING  │
     │ ・データ連結 │
     │ ・LLM生成   │
     └──────┬──────┘
            ↓
     ┌─────────────┐
     │   OUTPUT    │
     │ ・バッファ確認│
     │ ・OSC送信   │
     │ ・TTS再生   │
     └──────┬──────┘
            ↓
     ┌─────────────┐
     │   RESTING   │ (1秒)
     │  ・待機     │
     └──────┬──────┘
            ↓
       (RECEIVINGに戻る)
```

### 2.3 データ構造

```python
@dataclass
class BIInputData:
    timestamp: float        # UNIX timestamp
    text: str              # 入力テキスト
    source_type: str       # "human" or "BI"
    lang: str             # 言語コード
```

---

## 3. 実装済み機能

### 3.1 コア機能（✅ 完了）
- [x] BIControllerクラス（4段階サイクル処理）
- [x] AppControllerクラス（OSCサーバー管理）
- [x] BIInputDataモデル
- [x] Soft Prefix生成ユーティリティ
- [x] モジュール分離（app/, bi/ディレクトリ）

### 3.2 OSCエンドポイント（✅ 完了）
- [x] `/bi/input` - 入力データ受付
- [x] `/bi/stop` - サイクル停止
- [x] `/bi/status` - ステータス取得
- [x] 自動起動 - アプリケーション起動時にサイクルが自動開始
- [x] `/mixer` - Mixer PCへの生成テキスト送信

### 3.3 設定ファイル（✅ 完了）
- [x] サイクル設定（receive_duration, rest_duration, max_data_age）
- [x] ターゲットデバイスリスト（networks.csv）
- [x] Mixer PC設定（host, port）

### 3.4 データフィルタリング（✅ 完了）
- [x] タイムスタンプによる古いデータ破棄
- [x] 時系列順データ連結

---

## 4. 実装の重要ポイント

### 4.1 非同期処理
- asyncio ベースのイベントループ
- OSCサーバーとBIサイクルの並行動作
- StackFlow TCP通信の非同期処理

### 4.2 エラーハンドリング
- 各フェーズでの例外キャッチ
- StackFlow接続エラー時の再接続
- 詳細なログ出力（loguru使用）

### 4.3 状態管理
- BIControllerの状態遷移管理
- 入力バッファの適切なクリア
- タイムスタンプベースのデータ有効期限管理

---

## 5. 技術的な考慮事項

### 5.1 パフォーマンス
- LLM推論速度: 目標1秒以内
- TTS生成速度: 目標1秒以内に再生開始
- サイクル全体: 約5~8秒

### 5.2 拡張性
- 新規言語追加が容易（LLM_SETTINGSに追加）
- モデル切り替えが設定ファイルで可能
- 送信先デバイスの動的追加対応

### 5.3 保守性
- モジュール化されたアーキテクチャ
- 型ヒントによる可読性向上
- 詳細なログ出力

---

## 6. TTS音声出力のWAVファイル化計画（v2.1）

### 6.1 背景と目的
- **現状**: TTS音声はStackFlow経由で直接スピーカーに出力（`enaudio: True`）
- **課題**: 音声ファイルが保存されず、後処理（エフェクト適用など）ができない
- **目的**: WAVファイル書き出し→FFmpeg変換（オプション）→tinyplay再生に変更

### 6.2 技術調査結果
- ✅ StackFlowはOpenAI互換API（`http://127.0.0.1:8000/v1`）を提供
- ✅ `response_format="wav"` でWAVファイル出力が可能（[tests/tts_openai.py](tests/tts_openai.py) で確認）
- ✅ FFmpegによるフォーマット変換が可能
- ✅ tinyplayコマンドで再生可能（M5Stack環境で利用可能）

### 6.3 実装アプローチ

#### 6.3.1 処理フロー
```
1. OpenAI互換API経由でWAVファイル生成（/tmp/tts_output.wav）
   ↓
2. FFmpeg変換（オプション）
   - tinyplay互換フォーマットに変換（sample_rate, channels, sample_format）
   - ランブルエフェクト適用（オプション）
   ↓
3. tinyplayコマンドで再生
   - カード・デバイス番号指定
   ↓
4. 一時ファイル削除
```

#### 6.3.2 実装対象ファイル

**api/tts.py の拡張**
- `http_post_json()`: HTTPリクエスト送信ユーティリティ
- `tts_generate_wav()`: OpenAI互換API経由でWAV生成
- `ffmpeg_convert_for_tinyplay()`: FFmpeg変換（基本）
- `ffmpeg_convert_for_tinyplay_with_rumble()`: FFmpeg変換＋ランブルエフェクト
- `tinyplay_play()`: tinyplayコマンド実行
- `StackFlowTTSClient.speak_to_file()`: WAVファイル書き出し→再生の統合メソッド

**bi/controller.py の変更**
- `_output_phase()`: `speak()` → `speak_to_file()` に変更

**config/config.json の拡張**
```json
"audio": {
  "tinyplay_card": 0,
  "tinyplay_device": 1,
  "sample_rate": 16000,
  "channels": 1,
  "sample_format": "s16",
  "enable_ffmpeg_convert": true,
  "enable_rumble_effect": false,
  "temp_wav_dir": "/tmp"
}
```

### 6.4 実装タスク

#### Phase 1: コア機能実装 ✅
- [x] `api/tts.py`にWAVファイル生成・変換・再生機能を追加
  - `tts_generate_wav()`: OpenAI互換API経由でWAV生成
  - `ffmpeg_convert_for_tinyplay()`: FFmpeg変換（基本）
  - `ffmpeg_convert_for_tinyplay_with_rumble()`: FFmpeg変換＋ランブルエフェクト
  - `tinyplay_play()`: tinyplayコマンド実行
- [x] 一時ファイル管理（作成・削除）
- [x] エラーハンドリング（ファイルI/O、FFmpeg、tinyplayエラー）

#### Phase 2: 統合 ✅
- [x] `StackFlowTTSClient.speak_to_file()`メソッドの実装
- [x] `bi/controller.py`の`_output_phase()`を変更（`speak()` → `speak_to_file()`）
- [x] 設定ファイル拡張（`config.json`に`audio`セクション追加）
- [x] 依存関係追加（`pyproject.toml`に`aiohttp`追加）

#### Phase 3: テスト・最適化
- [x] 単体テスト（WAV生成、FFmpeg変換、tinyplay再生） - `tests/test_tts_wav_playback.py`
- [ ] 統合テスト（BIサイクル全体）- 実機での動作確認が必要
- [ ] パフォーマンス測定（1秒以内に再生開始の目標達成確認）- 実機での測定が必要

### 6.5 技術的な考慮事項

#### 6.5.1 パフォーマンス
- **目標**: 1秒以内に再生開始
- **リスク**: ファイルI/O、FFmpeg変換のオーバーヘッド
- **対策**:
  - FFmpeg変換をオプション化（`enable_ffmpeg_convert`）
  - 一時ファイルを`/tmp`（メモリベースのtmpfs）に配置
  - 非同期処理（`asyncio.create_subprocess_exec`）の活用

#### 6.5.2 エラーハンドリング
- ファイルI/Oエラー（ディスク容量不足など）
- FFmpegコマンドエラー（インストール未確認、引数エラー）
- tinyplayコマンドエラー（デバイス番号不正など）
- → 各段階で例外キャッチし、ログ出力

#### 6.5.3 依存関係
- **FFmpeg**: システムにインストール済みか確認（`ffmpeg -version`）
- **tinyplay**: M5Stack環境で利用可能か確認
- **OpenAI互換API**: StackFlowが起動しているか確認

### 6.6 後方互換性
- 既存の`speak()`メソッドは残す（直接再生が必要な場合のフォールバック）
- 設定ファイルで動作モード切り替え可能にする（`use_file_output: true/false`）

### 6.7 将来的な拡張
- ランブルエフェクトのパラメータ調整機能
- 複数エフェクトの追加（リバーブ、イコライザーなど）
- WAVファイルのアーカイブ機能（デバッグ用）
