# 植物センサー統合

植物センサー統合システムは、クロロフィル蛍光（CF）とAcoustic Emission（AE）センサーからデータを取得し、2次元マトリクスに基づいてSoft Prefix値を動的に決定してBIシステムに送信します。

---

## 概要

### 主な機能

- **クロロフィル蛍光（CF）測定**: 植物の光合成効率を示すPFI（Photosynthetic Fitness Index）値を取得
- **Acoustic Emission（AE）測定**: 植物の音響放射を検出
- **2次元マトリクス**: AE×CFの状態に応じてSoft Prefix値を決定
- **自動OSC送信**: `/bi/soft_prefix_update`エンドポイント経由でBIシステムに通知
- **LEDパフォーマンス**: Soft Prefix更新時にLEDフェードアニメーションをトリガー

### システム構成

```
[CFデバイス: 10.0.0.211-212]
    ↓ OSC (/cf/data)
[植物センサーサーバー: 0.0.0.0:8000]
    ↓
[AE×CFマトリクス処理]
    ↓ soft_prefix値決定
[OSC送信: /bi/soft_prefix_update]
    ↓
[Mac: 10.0.0.202] → [BIデバイス群]
```

---

## 設定ファイル

### config/plant_sensor_config.json

```json
{
  "_desc": "植物センサー → soft_prefix → Mac(10.0.0.202) 配信設定",

  "listen_ip": "0.0.0.0",          // OSC受信IP
  "listen_port": 8000,             // OSC受信ポート

  "relay_target": {
    "_desc": "soft_prefix 付き /bi/input を送る先 (Mac が M5Stack へ中継)",
    "host": "10.0.0.202",          // Mac（中継サーバー）のIP
    "port": 8000                   // 送信先ポート
  },

  "soft_prefix_p": 1,              // Soft Prefix P次元
  "soft_prefix_h": 1536,           // Soft Prefix H次元（TinySwallow-1.5B）
  "min_send_interval_sec": 3.0,    // 最小送信間隔（秒）

  // クロロフィル蛍光（CF）デバイス
  "cf_devices": {
    "_desc": "クロロフィル蛍光(CF)デバイス",
    "CF00": { "source_ip": "10.0.0.211" },
    "CF01": { "source_ip": "10.0.0.212" }
  },

  // Acoustic Emission（AE）センサー
  "ae_sensor": {
    "_desc": "AEセンサー。手動DLしたCSVを ae_csv/ に配置",
    "enabled": true,               // AEセンサーの有効/無効
    "csv_dir": "ae_csv",           // CSVファイルディレクトリ
    "poll_interval_sec": 30,       // ポーリング間隔（秒）
    "ae_column": "AE",             // CSV内のAEカラム名
    "max_ae_count": 200            // 最大AEカウント（正規化の上限）
  },

  // AE×CF → soft_prefix 2軸マトリクス
  "matrix": {
    "_desc": "=== AE×CF → soft_prefix 2軸マトリクス ===",
    "_desc2": "全状態が強い影響。植物の状態で揺らぎの'性格'が変わる",

    "ae_thresholds": [0.33, 0.66],
    "_desc_ae": "AE正規化値の境界 → [低, 中, 高] の3段階",

    "cf_thresholds": [-0.3, 0.3],
    "_desc_cf": "PFI値の境界 → [悪化, 安定, 良化] の3段階",

    "values": {
      "_desc": "matrix[AE段階][CF段階] → soft_prefix BF16値",
      "_desc_meaning": "1e-3=収束的(硬い揺らぎ) → 1e-2=発散的(自由な揺らぎ)",
      "low_worse":    0.001,       // AE低×CF悪化
      "low_stable":   0.003,       // AE低×CF安定
      "low_better":   0.007,       // AE低×CF良化
      "mid_worse":    0.003,       // AE中×CF悪化
      "mid_stable":   0.007,       // AE中×CF安定
      "mid_better":   0.01,        // AE中×CF良化
      "high_worse":   0.007,       // AE高×CF悪化
      "high_stable":  0.01,        // AE高×CF安定
      "high_better":  0.01         // AE高×CF良化
    }
  }
}
```

---

## AE×CFマトリクス

### 2次元マトリクスの概念

植物の状態を2軸で表現し、それぞれの状態に応じたSoft Prefix値を設定：

```
       CF軸（光合成効率）
        悪化  安定  良化
      ┌─────┬─────┬─────┐
  低  │0.001│0.003│0.007│  AE軸
      ├─────┼─────┼─────┤ （音響放射）
  中  │0.003│0.007│0.01 │
      ├─────┼─────┼─────┤
  高  │0.007│0.01 │0.01 │
      └─────┴─────┴─────┘
```

### マトリクスの意味

**Soft Prefix値の解釈**:
- **低い値（1e-3）**: 収束的な揺らぎ、硬い応答
- **高い値（1e-2）**: 発散的な揺らぎ、自由な応答

**植物の状態とSoft Prefix**:
- **AE低×CF悪化** (0.001): 植物が静かで光合成が弱い → 収束的な揺らぎ
- **AE高×CF良化** (0.01): 植物が活発で光合成が強い → 発散的な揺らぎ
- **その他**: 中間的な状態

### AE段階の決定

AE値を正規化（0-1）し、閾値で3段階に分類：

```python
ae_normalized = ae_count / max_ae_count  # 例: 100 / 200 = 0.5

if ae_normalized < 0.33:
    ae_level = "low"    # 低
elif ae_normalized < 0.66:
    ae_level = "mid"    # 中
else:
    ae_level = "high"   # 高
```

### CF段階の決定

PFI値（Photosynthetic Fitness Index）を閾値で3段階に分類：

```python
pfi_value = cf_data["pfi"]  # 例: 0.5

if pfi_value < -0.3:
    cf_level = "worse"   # 悪化
elif pfi_value < 0.3:
    cf_level = "stable"  # 安定
else:
    cf_level = "better"  # 良化
```

### Soft Prefix値の選択

AEとCFの段階からマトリクス値を選択：

```python
key = f"{ae_level}_{cf_level}"  # 例: "mid_stable"
soft_prefix_val = matrix_values[key]  # 例: 0.007
```

---

## クロロフィル蛍光（CF）デバイス

### データフォーマット

CFデバイスは、OSC経由で以下のデータを送信：

```
OSCアドレス: /cf/data
引数:
  - device_id (str): デバイスID（例: "CF00"）
  - pfi (float): Photosynthetic Fitness Index（-1.0 ~ 1.0）
  - timestamp (int): タイムスタンプ（Unix時間）
```

### デバイス設定

```json
"cf_devices": {
  "CF00": { "source_ip": "10.0.0.211" },  // デバイス1
  "CF01": { "source_ip": "10.0.0.212" }   // デバイス2
}
```

### PFI値の意味

- **PFI > 0.3**: 光合成が良化している（植物が健康）
- **-0.3 ≤ PFI ≤ 0.3**: 光合成が安定している
- **PFI < -0.3**: 光合成が悪化している（植物がストレス状態）

---

## Acoustic Emission（AE）センサー

### データフォーマット

AEセンサーは、CSVファイル経由でデータを提供：

```csv
timestamp,AE
2024-01-01 12:00:00,45
2024-01-01 12:00:30,52
2024-01-01 12:01:00,60
...
```

### CSV読み込み

```python
csv_dir = "ae_csv"
poll_interval_sec = 30  # 30秒ごとにCSVをチェック
ae_column = "AE"        # CSVのAEカラム
max_ae_count = 200      # 正規化の上限
```

### AEカウントの意味

- **AE値**: 植物の音響放射回数（高いほど活発）
- **正規化**: `ae_normalized = ae_count / max_ae_count`
- **0.0 ~ 0.33**: 静か（低活性）
- **0.33 ~ 0.66**: 通常（中活性）
- **0.66 ~ 1.0**: 活発（高活性）

---

## OSC通信

### 受信エンドポイント

植物センサーサーバーが受信：

| エンドポイント | 引数 | 送信元 |
|------------|------|--------|
| `/cf/data` | device_id, pfi, timestamp | CFデバイス（10.0.0.211-212） |

### 送信エンドポイント

植物センサーサーバーが送信：

| エンドポイント | 引数 | 送信先 |
|------------|------|--------|
| `/bi/soft_prefix_update` | soft_prefix_val, cf_value, ae_value | Mac（10.0.0.202） |

### `/bi/soft_prefix_update`の引数

```python
soft_prefix_val (float): マトリクスから決定されたSoft Prefix値（例: 0.007）
cf_value (float): 最新のPFI値（例: 0.5）
ae_value (float): 最新のAE正規化値（例: 0.5）
```

---

## 動作フロー

### 初期化

```
1. 設定ファイル読み込み（plant_sensor_config.json）
2. OSCサーバー起動（0.0.0.0:8000）
3. AEセンサーポーリング開始（30秒間隔）
```

### CFデータ受信時

```
1. /cf/data 受信（CFデバイスから）
   ↓
2. PFI値を保存（最新値として）
   ↓
3. CF段階を決定（worse/stable/better）
   ↓
4. AE段階と組み合わせてマトリクス値を選択
   ↓
5. 送信間隔チェック（min_send_interval_sec）
   ↓ OK
6. /bi/soft_prefix_update 送信（Mac: 10.0.0.202へ）
   ↓
7. BIシステムがSoft Prefix値を更新
   ↓
8. LEDパフォーマンスがトリガーされる
```

### AEデータポーリング

```
1. 30秒ごとにCSVファイルをチェック
   ↓
2. 最新のAEカウントを取得
   ↓
3. AE段階を決定（low/mid/high）
   ↓
4. CF段階と組み合わせてマトリクス値を更新
```

---

## 起動方法

### 植物センサーサーバーの起動

```bash
# 植物センサーサーバーを起動
python plant_sensor_server.py --config config/plant_sensor_config.json

# バックグラウンドで起動（tmux使用）
tmux new -s plant-sensor
python plant_sensor_server.py --config config/plant_sensor_config.json
# Ctrl+b → d でデタッチ
```

### AE CSVファイルの配置

```bash
# CSVディレクトリを作成
mkdir ae_csv

# CSVファイルを配置
# ae_csv/latest.csv
# または
# ae_csv/2024-01-01.csv
```

---

## トラブルシューティング

### CFデバイスからデータが来ない

```bash
# CFデバイスのIPアドレスを確認
ping 10.0.0.211
ping 10.0.0.212

# OSC受信ポートを確認
netstat -an | grep 8000
```

### AEセンサーデータが読み込めない

```bash
# CSVファイルの存在を確認
ls -la ae_csv/

# CSVフォーマットを確認
head ae_csv/latest.csv
```

### Soft Prefix更新が送信されない

```bash
# 送信間隔を確認
"min_send_interval_sec": 3.0  # 3秒未満は送信されない

# 送信先を確認
"relay_target": {
  "host": "10.0.0.202",  # Macの正しいIP
  "port": 8000
}
```

---

## 開発者向け情報

### マトリクス値のチューニング

植物の状態に応じてSoft Prefix値を調整することで、LLM生成の「性格」を変化させることができます：

- **収束的な揺らぎ（低い値）**: 安定した、予測可能な生成
- **発散的な揺らぎ（高い値）**: 創造的な、予測不可能な生成

```json
"values": {
  "low_worse":    0.001,  // 最も収束的
  "low_stable":   0.003,
  "low_better":   0.007,
  "mid_worse":    0.003,
  "mid_stable":   0.007,
  "mid_better":   0.01,
  "high_worse":   0.007,
  "high_stable":  0.01,
  "high_better":  0.01    // 最も発散的
}
```

### 閾値の調整

AEとCFの閾値を調整することで、状態の境界を変更できます：

```json
"ae_thresholds": [0.33, 0.66],  // [低, 中, 高] の境界
"cf_thresholds": [-0.3, 0.3],   // [悪化, 安定, 良化] の境界
```

---

## 関連ドキュメント

- **メインシステム**: [docs/requirements.md](requirements.md)
- **Input Controller**: [docs/input_controller.md](input_controller.md)
- **LED制御**: [pca9685_osc_led_server.py](../pca9685_osc_led_server.py)
