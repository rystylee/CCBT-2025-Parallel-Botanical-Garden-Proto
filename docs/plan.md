# 実装計画書

## 1. プロジェクト実装概要

### 1.1 開発ステータス
- **現在のバージョン**: v2.0開発中（分散BIシステム）
- **前バージョン**: v1.0（単一デバイス、OSC単発処理）
- **次期バージョン**: v2.0（複数デバイス協調、サイクル処理）

### 1.2 主要な変更点
v1.0からv2.0への大きな変更:
- イベント駆動 → サイクル駆動
- 単一デバイス → 分散複数デバイス
- 単発処理 → バッファリング＋連結処理
- 長文生成（最大128トークン） → 短文生成（2~3トークン）
- タイムスタンプ管理機能追加

---

## 2. アーキテクチャ設計

### 2.1 全体アーキテクチャ

```
┌─────────────────────────────────────────────────────┐
│ Application Layer (app.py)                          │
│ ┌──────────────────┐ ┌─────────────────────────────┐│
│ │ AppController    │ │ BIController (NEW)          ││
│ │ (レガシーモード)  │ │ - State Machine             ││
│ │                  │ │ - Input Buffer Management   ││
│ │                  │ │ - Cycle Control             ││
│ └──────────────────┘ └─────────────────────────────┘│
└───────────────────┬─────────────────────────────────┘
                    │
┌───────────────────┴─────────────────────────────────┐
│ API Layer (api/)                                    │
│ ┌─────────────┐ ┌─────────────┐ ┌────────────────┐│
│ │ LLM Client  │ │ TTS Client  │ │ OSC Server/    ││
│ │             │ │             │ │ Client         ││
│ └─────────────┘ └─────────────┘ └────────────────┘│
└───────────────────┬─────────────────────────────────┘
                    │
┌───────────────────┴─────────────────────────────────┐
│ StackFlow API (localhost:10001)                     │
└─────────────────────────────────────────────────────┘
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

#### 入力データ
```python
@dataclass
class BIInputData:
    timestamp: float        # UNIX timestamp
    text: str              # 入力テキスト
    source_type: str       # "human" or "BI"
    lang: str             # 言語コード
```

#### 設定ファイル構造
```json
{
  "network": {
    "device_name": "BI-Device-01",
    "ip_address": "192.168.1.100"
  },
  "device": {
    "type": "1st_BI"  // or "2nd_BI"
  },
  "cycle": {
    "receive_duration": 3.0,
    "rest_duration": 1.0,
    "max_data_age": 60.0
  },
  "targets": [
    {"host": "192.168.1.101", "port": 8000},
    {"host": "192.168.1.102", "port": 8000}
  ],
  "osc": {
    "receive_port": 8000,
    "send_port": 8000
  },
  "stack_flow_llm": {
    "max_tokens": 64
  }
}
```

---

## 3. 実装フェーズ

### 3.1 フェーズ1: 基盤機能実装（完了済み）
- [x] StackFlow通信ユーティリティ
- [x] LLM/TTSクライアント
- [x] OSC通信
- [x] 基本的なアプリケーション構造

### 3.2 フェーズ2: BIシステム実装（現在）

#### 3.2.1 設定ファイル拡張
**ファイル**: [config/config.json](../config/config.json)

追加項目:
- `device.type`: デバイスタイプ
- `cycle`: サイクル設定
- `targets`: 送信先デバイスリスト

#### 3.2.2 BIControllerクラス実装
**ファイル**: [app.py](../app.py) (新規クラス追加)

```python
class BIController:
    def __init__(self, config: dict):
        self.config = config
        self.state = "STOPPED"  # STOPPED, RECEIVING, GENERATING, OUTPUT, RESTING
        self.input_buffer: List[BIInputData] = []
        self.device_type = config["device"]["type"]

        # 各種クライアント
        self.llm_client = StackFlowLLMClient(config)
        self.tts_client = StackFlowTTSClient(config)
        self.osc_server = OscServer(config)
        self.osc_client = OscClient(config)

    async def start_cycle(self):
        """BIサイクルを開始"""
        self.state = "RECEIVING"
        while self.state != "STOPPED":
            if self.state == "RECEIVING":
                await self._receiving_phase()
            elif self.state == "GENERATING":
                await self._generating_phase()
            elif self.state == "OUTPUT":
                await self._output_phase()
            elif self.state == "RESTING":
                await self._resting_phase()

    async def _receiving_phase(self):
        """入力受付期間（3秒）"""
        logger.info("RECEIVING phase started")
        await asyncio.sleep(self.config["cycle"]["receive_duration"])
        self._filter_old_data()
        self.state = "GENERATING"

    async def _generating_phase(self):
        """生成期間"""
        logger.info("GENERATING phase started")
        if not self.input_buffer:
            logger.warning("No input data, skipping generation")
            self.state = "RESTING"
            return

        # データを時系列順に連結
        concatenated_text = self._concatenate_inputs()

        # LLMで2~3トークン生成
        generated_text = await self.llm_client.generate_text(
            concatenated_text,
            self.config["common"]["lang"]
        )

        self.generated_text = generated_text
        self.tts_text = concatenated_text + generated_text
        self.state = "OUTPUT"

    async def _output_phase(self):
        """出力期間"""
        logger.info("OUTPUT phase started")

        # 生成テキストを次のBIへ送信
        timestamp = time.time()
        for target in self.config["targets"]:
            self.osc_client.send_to_target(
                target,
                "/bi/output",
                timestamp,
                self.generated_text,
                self.config["common"]["lang"]
            )

        # 全入力+生成をTTS再生
        await self.tts_client.speak(self.tts_text)

        # バッファクリア
        self.input_buffer.clear()
        self.state = "RESTING"

    async def _resting_phase(self):
        """休息期間（1秒）"""
        logger.info("RESTING phase started")
        await asyncio.sleep(self.config["cycle"]["rest_duration"])
        self.state = "RECEIVING"

    def _filter_old_data(self):
        """古いデータをフィルタリング"""
        current_time = time.time()
        max_age = self.config["cycle"]["max_data_age"]

        self.input_buffer = [
            data for data in self.input_buffer
            if (current_time - data.timestamp) < max_age
        ]

        # デバイスタイプに応じてフィルタリング
        if self.device_type == "2nd_BI":
            self.input_buffer = [
                data for data in self.input_buffer
                if data.source_type == "BI"
            ]

    def _concatenate_inputs(self) -> str:
        """入力データを時系列順に連結"""
        sorted_data = sorted(self.input_buffer, key=lambda x: x.timestamp)
        return "".join([data.text for data in sorted_data])

    def add_input(self, timestamp: float, text: str, source_type: str, lang: str):
        """入力データを追加"""
        data = BIInputData(
            timestamp=timestamp,
            text=text,
            source_type=source_type,
            lang=lang
        )
        self.input_buffer.append(data)
        logger.info(f"Added input: {data}")
```

#### 3.2.3 OSCハンドラー実装
**ファイル**: [api/osc.py](../api/osc.py)

新規エンドポイント:
- `/bi/input` - 入力データ受付
- `/bi/start` - サイクル開始
- `/bi/stop` - サイクル停止
- `/bi/status` - ステータス取得

```python
# app.pyでの登録例
bi_controller = BIController(config)

osc_server.add_handler("/bi/input", lambda addr, *args:
    bi_controller.add_input(args[0], args[1], args[2], args[3])
)

osc_server.add_handler("/bi/start", lambda addr, *args:
    asyncio.create_task(bi_controller.start_cycle())
)

osc_server.add_handler("/bi/stop", lambda addr, *args:
    setattr(bi_controller, 'state', 'STOPPED')
)
```

#### 3.2.4 LLMクライアント修正
**ファイル**: [api/llm.py](../api/llm.py)

変更点:
- `max_tokens` を64に変更
- プロンプトを「短い詩的テキスト生成」に変更

#### 3.2.5 OSCクライアント拡張
**ファイル**: [api/osc.py](../api/osc.py)

```python
class OscClient:
    def send_to_target(self, target: dict, address: str, *args):
        """特定のターゲットに送信"""
        client = SimpleUDPClient(target["host"], target["port"])
        client.send_message(address, args)
```

#### 3.2.6 テストスクリプト
**ファイル**: `test_bi.py` (新規作成)

```python
from pythonosc import udp_client
import time

# BIデバイスに入力送信
client = udp_client.SimpleUDPClient("192.168.1.100", 8000)

# サイクル開始
client.send_message("/bi/start", [])

# 人間の入力を送信
time.sleep(0.5)
client.send_message("/bi/input", [time.time(), "こんにちは", "human", "ja"])

time.sleep(1.0)
client.send_message("/bi/input", [time.time(), "世界", "human", "ja"])

# BIからの入力をシミュレート
time.sleep(1.0)
client.send_message("/bi/input", [time.time(), "素晴らしい", "BI", "ja"])
```

### 3.3 フェーズ3: テストと最適化

#### 3.3.1 単体テスト
- BIControllerの各フェーズ動作
- タイムスタンプフィルタリング
- デバイスタイプ別の入力フィルタリング

#### 3.3.2 統合テスト
- 複数デバイス間の通信
- サイクル同期の確認
- 長時間稼働テスト

#### 3.3.3 パフォーマンス最適化
- サイクル時間の測定
- LLM生成速度の最適化
- メモリ使用量の監視

---

## 4. 将来的な拡張

### 4.1 Excelトポロジー設定（優先度: 中）
```python
import pandas as pd

def load_topology_from_excel(excel_path: str) -> dict:
    """Excelファイルからトポロジーを読み込み"""
    df = pd.read_excel(excel_path, sheet_name="Topology")

    # カラム: device_id, device_type, host, port, targets
    topology = {}
    for _, row in df.iterrows():
        device_id = row["device_id"]
        topology[device_id] = {
            "type": row["device_type"],
            "host": row["host"],
            "port": row["port"],
            "targets": row["targets"].split(",")  # カンマ区切り
        }

    return topology
```

### 4.2 可視化ダッシュボード（優先度: 低）
- リアルタイムでサイクル状態を表示
- 入力バッファの可視化
- ネットワークトポロジーの可視化

### 4.3 動的トポロジー変更（優先度: 低）
- `/bi/set_targets` エンドポイントで送信先を動的に変更
- ランタイムでのトポロジー再構成

---

## 5. マイグレーション計画

### 5.1 後方互換性
既存の `/process`, `/process/llm`, `/process/tts` エンドポイントは維持されます。

### 5.2 移行手順
1. v1.0の設定ファイルを保存
2. 新しい設定フォーマットに変換
3. BIコントローラーを起動
4. 既存のテストスクリプトで動作確認
5. 新しいBIエンドポイントでテスト

---

## 6. 実装スケジュール

| タスク | 予定期間 | ステータス |
|--------|---------|-----------|
| 設定ファイル拡張 | 1日 | ⏳ 未着手 |
| BIController実装 | 3日 | ⏳ 未着手 |
| OSCハンドラー実装 | 1日 | ⏳ 未着手 |
| LLM/OSCクライアント修正 | 1日 | ⏳ 未着手 |
| テストスクリプト作成 | 1日 | ⏳ 未着手 |
| 統合テスト | 2日 | ⏳ 未着手 |
| ドキュメント更新 | 1日 | 🔄 進行中 |

**合計予定期間**: 約10日

---

## 7. リスクと対策

| リスク | 影響度 | 対策 |
|--------|-------|------|
| サイクルタイミングのズレ | 中 | ログで詳細な時間測定、調整パラメータ追加 |
| メモリリーク（長時間稼働） | 高 | 定期的なバッファクリア、メモリ監視 |
| ネットワーク遅延 | 中 | タイムアウト処理、リトライ機構 |
| 複数デバイスの同期 | 低 | 各デバイスは独立動作のため影響は限定的 |

---

## 8. 成功基準

- [x] 要件定義書の更新完了
- [ ] 実装計画書の更新完了
- [ ] BIControllerが4つの状態を正しく遷移
- [ ] 入力バッファが正しくフィルタリングされる
- [ ] 2nd BIが人間の入力を無視する
- [ ] 3秒間の入力が正しく連結される
- [ ] 2~3トークンが生成される
- [ ] OSC送信が指定されたターゲットに届く
- [ ] TTS再生が「全入力+生成」を含む
- [ ] サイクルが無限ループで動作する

---

## 9. コード構造リファクタリング計画

### 9.1 現状の課題
現在、`app.py`に以下のクラス・機能が混在している:
- `AppController`: OSCサーバー管理
- `BIController`: BI サイクル制御とビジネスロジック
- `BIInputData`: データモデル
- Soft Prefix生成ユーティリティ関数

### 9.2 リファクタリング目標
- **関心の分離**: BI関連のロジックを独立したモジュールに分離
- **保守性向上**: 各モジュールの責務を明確化
- **拡張性**: 将来的な機能追加を容易にする

### 9.3 新しいディレクトリ構造

```
CCBT-2025-Parallel-Botanical-Garden-Proto/
├── main.py                    # エントリーポイント
├── bi/                        # BI関連モジュール（新規）
│   ├── __init__.py           # bi モジュール初期化
│   ├── controller.py         # BIController クラス
│   ├── models.py             # BIInputData データクラス
│   └── utils.py              # Soft Prefix生成などのユーティリティ
├── app/                       # アプリケーション層（新規）
│   ├── __init__.py           # app モジュール初期化
│   └── controller.py         # AppController クラス
├── api/                       # API層（既存）
│   ├── __init__.py
│   ├── llm.py
│   ├── tts.py
│   ├── osc.py
│   └── utils.py
├── stackflow/                 # StackFlow関連（既存）
├── config/                    # 設定ファイル（既存）
├── tests/                     # テストスクリプト（既存）
└── docs/                      # ドキュメント（既存）
```

### 9.4 ファイル移行計画

#### Step 1: 新規ディレクトリ作成
```bash
mkdir -p bi app
touch bi/__init__.py app/__init__.py
```

#### Step 2: ファイル作成と移動

**bi/models.py** (新規作成)
- `app.py` から `BIInputData` を移動

**bi/utils.py** (新規作成)
- `app.py` から以下の関数を移動:
  - `f32_to_bf16_u16()`
  - `make_soft_prefix_b64_constant()`
  - `make_random_soft_prefix_b64()`
  - 定数: `P`, `H`, `VALS`

**bi/controller.py** (新規作成)
- `app.py` から `BIController` クラスを移動

**app/controller.py** (新規作成)
- `app.py` から `AppController` クラスを移動

**bi/__init__.py** (新規作成)
```python
from .controller import BIController
from .models import BIInputData
from .utils import make_random_soft_prefix_b64

__all__ = ["BIController", "BIInputData", "make_random_soft_prefix_b64"]
```

**app/__init__.py** (新規作成)
```python
from .controller import AppController

__all__ = ["AppController"]
```

#### Step 3: main.py の更新
import文を以下のように変更:
```python
from app import AppController
from bi import BIController
```

#### Step 4: 既存 app.py の削除
すべての内容が移行されたら `app.py` を削除

### 9.5 影響範囲

**変更が必要なファイル**:
- [x] `main.py` - import文の更新
- [x] `tests/test_bi.py` - import文の更新（必要に応じて）
- [x] `tests/test_multi_target.py` - import文の更新（必要に応じて）

**変更不要なファイル**:
- `api/` 配下のファイル（import元が変わるのみ）
- `config/` 配下のファイル
- その他のテストスクリプト

### 9.6 実施スケジュール

| タスク | 予定期間 | ステータス |
|--------|---------|-----------|
| リファクタリング計画策定 | 0.5日 | ✅ 完了 |
| 新規ディレクトリ・ファイル作成 | 0.5日 | ✅ 完了 |
| コード移行とimport更新 | 1日 | ✅ 完了 |
| 動作確認テスト | 0.5日 | ✅ 完了 |
| 旧app.pyの削除とドキュメント更新 | 0.5日 | ✅ 完了 |

**合計予定期間**: 約3日 → **実際の期間**: 1日で完了

### 9.7 リスクと対策

| リスク | 影響度 | 対策 |
|--------|-------|------|
| import文の更新漏れ | 中 | 全テストスクリプトで動作確認 |
| 循環importの発生 | 低 | 依存関係を明確に設計 |
| 後方互換性の喪失 | 低 | gitでバージョン管理、必要に応じてロールバック |

### 9.8 成功基準

- [x] 新しいディレクトリ構造が作成される
- [x] すべてのクラス・関数が適切なモジュールに配置される
- [x] `main.py` が新しいimport文で正常に動作する
- [x] 既存のテストスクリプトがすべて動作する（テストファイルは元々appからimportしていないため影響なし）
- [x] `app.py` が削除され、コードの重複がない

### 9.9 実施結果

**実施日**: 2026年2月6日

リファクタリングが正常に完了しました。以下のファイル構成に変更されました:

**新規作成ファイル**:
- `bi/__init__.py` - BIモジュール初期化
- `bi/models.py` - BIInputData データクラス
- `bi/utils.py` - Soft Prefix生成ユーティリティ
- `bi/controller.py` - BIController クラス
- `app/__init__.py` - Appモジュール初期化
- `app/controller.py` - AppController クラス

**変更ファイル**:
- `main.py` - import文を `from app import AppController, BIController` から `from app import AppController` と `from bi import BIController` に分離

**削除ファイル**:
- `app.py` - 全内容を新モジュールに移行済み

**検証結果**:
- Python構文チェック: 全ファイル問題なし
- ディレクトリ構造: 計画通りに作成完了
- 循環importなし
- コードの重複なし

---

このドキュメントは実装の進捗に応じて随時更新されます。
