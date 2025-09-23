# tools/llm-check — 言語別 LLM スモークテスト（ADB / push&run / CMake）

**目的**  
Mac から `adb` 経由で USB‑C 接続のデバイス（例：M5Stack LLM Compute Kit）に入って、選択言語に応じた **小型 LLM (GGUF)** をダウンロードし、
`llama.cpp` を **CMake** でビルドして **短い生成テスト**を実行します。デバイス側で Git を直接扱う必要はありません。

> このツールは **push&run 方式**（`adb push` → `adb shell sh /tmp/...`）なので、**PTY 必須の端末でも確実に終了**します。  
> 初回のみ「モデルDL + C++フルビルド」で **時間がかかります**。2回目以降は **推論だけ**で速くなります。

---

## サポート言語 → モデル（GGUF）

| LANG | モデル | 量子化 | Hugging Face |
|---|---|---:|---|
| JP | TinySwallow‑1.5B‑Instruct | Q5_K_M | `SakanaAI/TinySwallow-1.5B-Instruct-GGUF` |
| EN | Llama‑3.2‑1B‑Instruct | Q4_K_M | `bartowski/Llama-3.2-1B-Instruct-GGUF` |
| CN | Qwen2.5‑1.5B‑Instruct | Q5_K_M | `Qwen/Qwen2.5-1.5B-Instruct-GGUF` |
| FR | Llama‑3.2‑1B‑Instruct | Q4_K_M | `bartowski/Llama-3.2-1B-Instruct-GGUF` |

> 注：「TinyShallow」は一般に **TinySwallow** を指すため、ここでは TinySwallow を使用しています。

---

## 前提

- Mac に `adb`（Android Platform Tools）がインストール済み  
  未インストール: `brew install android-platform-tools`
- デバイス（Linux, Debian/Ubuntu 系想定）に `apt-get` があるとベスト
- ネット接続（モデルDLと `git clone` に利用）
- 空き容量 2GB 目安（モデル 0.8〜1.3GB + ビルド）

---

## 配置（推奨）

```
CCBT-2025-Parallel-Botanical-Garden-Proto/
└── tools/
    └── llm-check/
        ├── mac_llm_smoke.sh   # ← 実行ファイル（Macで叩く）
        └── README.md           # ← 本ファイル
```

---

## 使い方（初回はこれでOK）

> **初回は重い**ので、**ビルドのタイムアウトを無効化**して完走させるのが確実です。

```bash
cd tools/llm-check

# 例: 日本語（TinySwallow）でスモークテスト
LLM_BUILD_TIMEOUT=0 bash mac_llm_smoke.sh -l JP

# 英語
LLM_BUILD_TIMEOUT=0 bash mac_llm_smoke.sh -l EN

# 中国語
LLM_BUILD_TIMEOUT=0 bash mac_llm_smoke.sh -l CN

# フランス語
LLM_BUILD_TIMEOUT=0 bash mac_llm_smoke.sh -l FR
```

- **複数台接続時**: `-s <ADB_SERIAL>` を付けるか、`ADB_SERIAL` 環境変数を設定してください。  
  例: `LLM_BUILD_TIMEOUT=0 bash mac_llm_smoke.sh -l JP -s axera-ax620e`
- 正常終了のサイン（最後の行）：  
  `--- LLM SMOKE: DONE (LANG=JP, STATUS=OK, EXE=/usr/local/llm/bin/llama-cli)`

**出力**  
- 生成結果（デバイス上）: `/tmp/llm_smoke_<LANG>.txt`  
- ビルド詳細ログ: `/tmp/llm_build.log`  
- CMakeターゲット一覧: `/tmp/llm_targets.txt`

---

## オプション / 環境変数

- `-l JP|EN|CN|FR` … 言語を指定（必須）  
- `-s SERIAL` …… 複数台接続時の adb シリアル（または `ADB_SERIAL`）  
- `LLM_BUILD_TIMEOUT` … **ビルドのタイムアウト秒**（既定 `900`、`0` で無効。初回は `0` 推奨）

---

## 2回目以降は速い理由

- モデルは `/usr/local/llm/models/*.gguf` に保存され、**二度目以降は再DLしません**。  
- 実行ファイルは `/usr/local/llm/bin/llama-cli`（または `llama`）に保存され、**二度目以降はビルドしません**。  
- よって **推論だけ**が走ります。

> 逆に毎回ビルドが走る場合：実行ファイルを削除している／権限 (`+x`) が落ちている／CMake 構成を毎回掃除している、等を疑ってください。

---

## 進捗が止まって見える時は

初回ビルドは長く、**重い翻訳単位のコンパイル中は出力に変化が少ない**ことがあります。ハングかどうかは更新時刻で判断：

```bash
adb -s <SERIAL> shell "stat -c '%y %s' /tmp/llm_build.log"
# タイムスタンプやサイズが増えていれば進行中です
```

---

## トラブルシューティング

**A. タイムアウトで止まる**  
- 既定の 900 秒で切れた可能性：`LLM_BUILD_TIMEOUT=0` または `=1800` などへ。

**B. メモリ不足（OOM）っぽい**  
```bash
adb -s <SERIAL> shell "dmesg | grep -i -E 'oom|out of memory|killed process' | tail -n 10 || true"
```
- その場合は **並列数を下げる（-j1 のまま）**／生成トークン `-n` を 32 に落とす／軽い量子化を選ぶ。

**C. 実行ファイルができていない**  
```bash
adb -s <SERIAL> shell "ls -l /usr/local/llm/llama.cpp/build/bin || true"
adb -s <SERIAL> shell "ls -l /usr/local/llm/bin || true"
```
- `/usr/local/llm/bin/llama-cli` または `/usr/local/llm/bin/llama` があればOK。
- どちらも無い場合は `/tmp/llm_build.log` のエラー箇所を確認。

**D. デバイスを選べない / unauthorized**  
- デバイス側の USB デバッグ許可ダイアログを承認し、再実行。

**E. ディスク不足**  
```bash
adb -s <SERIAL> shell "df -h /usr/local/llm /tmp"
```

---

## さらに速くする小技（任意）

- **並列ビルドを上げる**（メモリに余裕があるとき）  
  スクリプト内の `-j1` を `-j2` に変更するとビルドが短縮します。  
  例（Mac）：`sed -i '' 's/-j1/ -j2/g' tools/llm-check/mac_llm_smoke.sh`

- **最適化を弱めてビルド高速化**  
  CMake の設定に `-DCMAKE_C_FLAGS_RELEASE='-O2' -DCMAKE_CXX_FLAGS_RELEASE='-O2'` を追加。

- **ccache を導入**（再ビルドが速くなる）  
  デバイスで `apt-get install -y ccache` の後、CMake に  
  `-DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache` を付与。

- **生成を早く終える**  
  出力長 `-n 64` を `-n 32` に下げる。

---

## 実装の要点（内部で行っていること）

1. `adb push` で `/tmp/llm_smoke_remote.sh` を転送 → `adb shell sh` で実行  
2. 依存が無ければ `apt-get` で `git build-essential cmake curl ca-certificates` を導入（best‑effort）  
3. `/usr/local/llm/llama.cpp` を `git clone`（未存在時）→ CMake で構成  
   - `-DLLAMA_BUILD_EXAMPLES=ON -DLLAMA_BUILD_SERVER=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_CURL=OFF -DGGML_OPENMP=OFF`  
4. CMake ターゲット一覧を確認し、**`llama-cli` → `llama` → `main`** の順にビルドを試行  
5. 見つかった実行ファイルを `/usr/local/llm/bin/` へ配置  
6. モデルを `/usr/local/llm/models/` にダウンロード（既存ならスキップ）  
7. `llama-cli`（または `llama`）で **64 トークン**の生成を実行し、結果を `/tmp/llm_smoke_<LANG>.txt` に保存

---

## 免責 / 注意

- モデル配布の各ライセンスに従ってください（Llama 3.2 は Meta ライセンス、Qwen/TinySwallow は Apache-2.0 等）。
- ネットワーク品質やデバイス性能により所要時間は変動します。初回は DL + フルビルドで長時間になることがあります。

以上です。初回は `LLM_BUILD_TIMEOUT=0` での実行を強く推奨します。
