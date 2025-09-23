# tools/audio-check — M5Stack Audio Check (ADB, Mac only)

このフォルダは、**Mac 上に既に clone 済みの**プライベートリポジトリ
`rystylee/CCBT-2025-Parallel-Botanical-Garden-Proto` 内で、
USB‑C で接続した M5Stack LLM Compute Kit の**オーディオ認識と発音確認**を
**Mac 側から adb 経由**で行うための最小ツールをまとめたものです。  
（デバイス側でリポジトリを clone する必要はありません）

---

## 目的（要約）

0. *（前提）* Mac には `CCBT-2025-Parallel-Botanical-Garden-Proto` が clone 済み  
1. Mac 側で adb の動作確認  
2. USB‑C 経由で M5Stack が adb で認識されているか確認  
3. 認識されていれば **Mac から**スクリプトを実行し、デバイス上で:
   - `alsa-utils`（`aplay`/`amixer`）の導入（未導入時のみ）
   - 再生デバイス自動検出（/proc/asound/pcm を優先）
   - ミュート解除＆音量設定（best-effort）
   - `/usr/local/m5stack/logo.wav` の再生（無ければ 48kHz テストトーン生成）

---

## 前提

- Mac に **adb**（Android Platform Tools）が入っていること  
  未インストールなら:  
  ```bash
  brew install android-platform-tools
  ```
- M5Stack と Mac が USB‑C で接続されていること
- M5Stack 側で root 権限があり、可能であれば `apt-get` が利用可能（無くても既に `aplay` があれば実行可）

---

## 使い方（最短）

```bash
# リポジトリ直下から
cd tools/audio-check

# 接続している M5Stack を自動検出して音出しまで実行
bash mac_audio_check.sh
```

デフォルトの再生ファイルは `/usr/local/m5stack/logo.wav` です。  
存在しない場合は、デバイス上で **48kHz/16bit/stereo の 440Hz テストWAV**を生成して再生します。

---

## オプション

```bash
bash mac_audio_check.sh [-w /path/to/file.wav] [-s SERIAL] [-h]
```

- `-w, --wav` … 再生する WAV のパス（デバイス上のパス）。省略時は `/usr/local/m5stack/logo.wav`  
- `-s, --serial` … 複数台接続時の adb デバイスシリアル。未指定時は 1 台のみ接続されている前提で自動選択  
  - もしくは環境変数 `ADB_SERIAL` を利用可能
- `-h, --help` … ヘルプ表示

**戻り値（exit code）**
- `0` … 再生成功  
- `1` … adb 認識なし / 複数台で選択未指定 / 再生失敗  
- `2` … WAV が無く、生成もできなかった（python3 不在 など）

---

## 実行内容（内部の流れ）

1. Mac で adb を確認、接続中デバイスのシリアルを確定  
2. デバイス側で `aplay` が無ければ `apt-get update && apt-get install -y alsa-utils`（失敗しても続行）  
3. `/proc/asound/pcm` から **最初の PLAYBACK** を `card,device` として抽出（無ければ `aplay -l`、最終手段で `0,1`）  
4. `amixer` または `tinymix` があればミュート解除＆音量UP（best-effort）  
5. 指定 WAV が無ければ python3 で 48kHz テストトーンを生成  
6. `aplay -D hw:card,device -f S16_LE -r 48000 -c 2` で再生（失敗時は `plughw:` にフォールバック）

---

## 典型的なトラブルと対処

- **`unauthorized`**（`adb devices` で）  
  → デバイス側の USB デバッグ許可ダイアログを承認のうえ、再度実行。

- **`Device or resource busy`**  
  → 数秒待ってリトライ、または `plughw:` での再試行をスクリプトが自動実施。

- **無音（エラーなし）**  
  → ボード依存のミキサ名により、`amixer` での一括設定が効かない場合があります。  
     その場合は `tinymix -D 0 controls` で名称を特定し、個別に開放してください。

---

## ディレクトリ構成（提案）

```
CCBT-2025-Parallel-Botanical-Garden-Proto/
└── tools/
    └── audio-check/
        ├── mac_audio_check.sh   # ← このスクリプト（Macで実行）
        └── README.md            # ← このファイル
```

このフォルダごとリポジトリに追加すれば、他メンバーも Mac 側から同手順でチェックできます。
