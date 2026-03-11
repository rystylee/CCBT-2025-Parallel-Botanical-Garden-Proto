# RECEIVING時のLED点滅機能追加

## 背景・目的

現状、システムは以下のフェーズで動作しているが、RECEIVINGフェーズではLEDが点灯していない：

- **RECEIVING**: OSCメッセージを受信する待機フェーズ（待機音のみ、LEDなし）
- **GENERATING**: LLMによるテキスト生成フェーズ（LED点滅あり）
- **OUTPUT**: TTS音声出力フェーズ（LEDフェードあり）
- **RESTING**: 休息フェーズ（LEDオフ）

ユーザー体験の向上のため、RECEIVINGフェーズでも**0.0～0.2の範囲で点滅させる**機能を追加する。

## 現状分析

### 現在のLED制御実装（bi/controller.py）

#### ステータス別のLED動作

| ステータス | LED動作 | 明るさ範囲 | 実装状況 |
|----------|---------|-----------|---------|
| RECEIVING | **なし** ❌ | - | 待機音のみ実装済み |
| GENERATING | 点滅 | 0.05～0.25 | 実装済み ✅ |
| OUTPUT | フェードアップ→ダウン | 0.0→1.0→0.0 | 実装済み ✅ |
| RESTING | オフ | 0.0 | 実装済み ✅ |

#### LED制御の主要メソッド

```python
# 476-528行目付近
async def _led_pulse_loop(self):
    """Continuously pulse LED between min and max brightness."""
    # 現在はgenerating_min_brightness (0.05) と generating_max_brightness (0.25) でハードコード
    min_brightness = led_config.get("generating_min_brightness", 0.2)
    max_brightness = led_config.get("generating_max_brightness", 0.6)
    # ... 点滅ループ処理
```

```python
# 82-93行目
async def _receiving_phase(self):
    """Phase 1: Receive input data for specified duration"""
    logger.info("RECEIVING phase started")

    # Start waiting audio loop
    await self._start_waiting_loop()  # 待機音のみ

    receive_duration = self.config.get("cycle", {}).get("receive_duration", 3.0)
    await asyncio.sleep(receive_duration)

    logger.info(f"Buffer size: {len(self.input_buffer)}")
    self.state = "GENERATING"
```

**問題点**: `_receiving_phase()`内でLED制御が一切呼び出されていない

### 現在のconfig.json設定（186-187行目付近）

```json
"led_control": {
  "enabled": true,
  "targets": [0],
  "generating_min_brightness": 0.05,
  "generating_max_brightness": 0.25,
  "fade_duration": 1.0,
  "pulse_interval": 1.5
}
```

## 実装方針

### 方針A: RECEIVING専用の点滅タスクを追加（推奨）

既存の`_led_pulse_loop()`メソッドを**パラメータ化**して、RECEIVINGとGENERATINGで異なる明るさ範囲を使用できるようにする。

#### メリット
- 既存のコード構造を活用できる
- GENERATINGの点滅（0.05～0.25）と明確に区別できる
- configで細かく調整可能
- コードの重複が最小限

#### デメリット
- `_led_pulse_loop()`のシグネチャ変更が必要

### 方針B: 別メソッドを作成

`_led_pulse_loop_receiving()`として完全に独立したメソッドを作成する。

#### メリット
- 既存コードへの影響が少ない

#### デメリット
- コードの重複が発生
- 保守性が低下

**→ 方針Aを採用**

## 修正箇所の詳細

### 1. config/config.json の修正

`led_control`セクションに以下を追加:

```json
"led_control": {
  "enabled": true,
  "targets": [0],
  "receiving_min_brightness": 0.0,      // 新規追加
  "receiving_max_brightness": 0.2,      // 新規追加
  "generating_min_brightness": 0.05,    // 既存（GENERATING用）
  "generating_max_brightness": 0.25,    // 既存（GENERATING用）
  "fade_duration": 1.0,
  "pulse_interval": 1.5
}
```

### 2. bi/controller.py の修正

#### 2-1. `_led_pulse_loop()` メソッドの修正（476-528行目付近）

**変更前:**
```python
async def _led_pulse_loop(self):
    """Continuously pulse LED between min and max brightness."""
    led_config = self.config.get("led_control", {})
    if not led_config.get("enabled", False):
        return

    targets = led_config.get("targets", [])
    if not targets:
        return

    min_brightness = led_config.get("generating_min_brightness", 0.2)
    max_brightness = led_config.get("generating_max_brightness", 0.6)
    # ... 以下点滅ループ
```

**変更後:**
```python
async def _led_pulse_loop(self, min_brightness=None, max_brightness=None):
    """Continuously pulse LED between min and max brightness.

    Args:
        min_brightness: Minimum brightness (0.0-1.0). If None, uses waiting_min_brightness from config.
        max_brightness: Maximum brightness (0.0-1.0). If None, uses waiting_max_brightness from config.
    """
    led_config = self.config.get("led_control", {})
    if not led_config.get("enabled", False):
        return

    targets = led_config.get("targets", [])
    if not targets:
        return

    # Use parameters or fall back to generating_ config (for GENERATING phase)
    if min_brightness is None:
        min_brightness = led_config.get("generating_min_brightness", 0.2)
    if max_brightness is None:
        max_brightness = led_config.get("generating_max_brightness", 0.6)

    # ... 以下は既存のロジックをそのまま使用
```

#### 2-2. `_receiving_phase()` メソッドの修正（82-93行目）

**変更前:**
```python
async def _receiving_phase(self):
    """Phase 1: Receive input data for specified duration"""
    logger.info("RECEIVING phase started")

    # Start waiting audio loop
    await self._start_waiting_loop()

    receive_duration = self.config.get("cycle", {}).get("receive_duration", 3.0)
    await asyncio.sleep(receive_duration)

    logger.info(f"Buffer size: {len(self.input_buffer)}")
    self.state = "GENERATING"
```

**変更後:**
```python
async def _receiving_phase(self):
    """Phase 1: Receive input data for specified duration"""
    logger.info("RECEIVING phase started")

    # Start LED pulsing for RECEIVING state
    led_config = self.config.get("led_control", {})
    if led_config.get("enabled", False):
        receiving_min = led_config.get("receiving_min_brightness", 0.0)
        receiving_max = led_config.get("receiving_max_brightness", 0.2)

        # Fade to receiving_max brightness
        await self._led_fade(0.0, receiving_max)

        # Start pulsing with RECEIVING-specific brightness range
        self._pulse_task = asyncio.create_task(
            self._led_pulse_loop(
                min_brightness=receiving_min,
                max_brightness=receiving_max
            )
        )

    # Start waiting audio loop
    await self._start_waiting_loop()

    receive_duration = self.config.get("cycle", {}).get("receive_duration", 3.0)
    await asyncio.sleep(receive_duration)

    # Stop pulsing before moving to GENERATING
    if led_config.get("enabled", False):
        await self._stop_pulse()

    logger.info(f"Buffer size: {len(self.input_buffer)}")
    self.state = "GENERATING"
```

#### 2-3. `_generating_phase()` の確認（95-122行目）

既存の実装では、GENERATING開始時に以下の処理を行っている:

```python
async def _generating_phase(self):
    """Phase 2: Generate poetic text using LLM"""
    logger.info("GENERATING phase started")

    # Start LED pulsing
    led_config = self.config.get("led_control", {})
    if led_config.get("enabled", False):
        generating_max = led_config.get("generating_max_brightness", 0.6)
        await self._led_fade(0.0, generating_max)  # ← RECEIVINGからの場合は0.0からではなく現在値から
        self._pulse_task = asyncio.create_task(self._led_pulse_loop())  # ← デフォルトパラメータを使用
```

**注意点**: RECEIVING→GENERATINGの遷移時、`_led_fade(0.0, waiting_max)`が実行されるため、一旦0.0にリセットされてから0.25まで上がる。スムーズな遷移が必要な場合は、現在の明るさから開始するよう修正することも検討できる。

## 期待される動作

| フェーズ | LED動作 | 明るさ範囲 | 音声 |
|---------|---------|-----------|------|
| **RECEIVING** | 点滅（新規） ✨ | 0.0～0.2 | 待機音ループ |
| **GENERATING** | 点滅（既存） | 0.05～0.25 | 待機音ループ |
| **OUTPUT** | フェードアップ→ダウン | 0.0→1.0→0.0 | TTS音声出力 |
| **RESTING** | オフ | 0.0 | なし |

### フェーズ遷移時のLED挙動

```
RECEIVING開始:
  0.0 → 0.2にフェード → 0.0～0.2で点滅開始

RECEIVING→GENERATING:
  点滅停止 → 0.0にリセット → 0.25にフェード → 0.05～0.25で点滅開始
  ※スムーズ遷移が必要な場合は別途調整

GENERATING→OUTPUT:
  点滅停止 → 1.0にフェード → 0.0にフェード

OUTPUT→RESTING:
  0.0を維持
```

## 実装時の注意点

1. **非同期タスクの管理**
   - `_pulse_task`の開始/停止を適切に行う
   - `_stop_pulse()`は既存メソッドを利用

2. **Config検証**
   - `receiving_min_brightness` < `receiving_max_brightness`を確認
   - 範囲は0.0～1.0内

3. **テスト**
   - 各フェーズのLED動作を目視確認
   - フェーズ遷移時のスムーズさを確認
   - config変更による調整が正しく反映されるか確認

4. **ログ出力**
   - RECEIVING開始時にLED点滅開始のログを追加
   - デバッグしやすいよう適切なログレベルで記録

## 今後の拡張可能性

- フェーズごとに異なる点滅パターン（正弦波、ランダムなど）
- 複数LEDチャンネルの個別制御
- OSCメッセージの強度に応じた明るさの動的変更
- config.jsonでフェーズごとのLED設定をネスト構造で管理

## 参考

- 実装ファイル: [bi/controller.py](../bi/controller.py)
- 設定ファイル: [config/config.json](../config/config.json)
- LED制御OSCサーバー: [pca9685_osc_led_server.py](../pca9685_osc_led_server.py)
