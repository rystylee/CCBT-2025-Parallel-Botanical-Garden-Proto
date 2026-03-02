# CCBT BI デバイス 起動時自動チェック セットアップガイド

電源を入れたら自動で LED / Audio / LLM / TTS の全機能チェックを実行し、ログを保存する仕組みです。

---

## ファイル構成

```
scripts/boot_check.sh          ← チェック実行＋ログ保存のラッパー
systemd/ccbt-bi-check.service  ← systemd サービス定義
```

---

## セットアップ手順

### 1. ファイルの配置

```bash
# プロジェクトディレクトリに boot_check.sh をコピー
cp scripts/boot_check.sh /home/m5stack/CCBT-2025-Parallel-Botanical-Garden-Proto/scripts/

# 実行権限を付与
chmod +x /home/m5stack/CCBT-2025-Parallel-Botanical-Garden-Proto/scripts/boot_check.sh
```

### 2. ログディレクトリの作成

```bash
sudo mkdir -p /var/log/ccbt-bi-check
sudo chown m5stack:m5stack /var/log/ccbt-bi-check
```

### 3. systemd サービスの登録

```bash
# サービスファイルをコピー
sudo cp systemd/ccbt-bi-check.service /etc/systemd/system/

# systemd をリロード
sudo systemctl daemon-reload

# 起動時に自動実行を有効化
sudo systemctl enable ccbt-bi-check.service
```

### 4. 動作確認（手動実行）

```bash
# サービスを手動で実行してテスト
sudo systemctl start ccbt-bi-check.service

# 実行状態の確認
sudo systemctl status ccbt-bi-check.service

# journalctl でログを確認
journalctl -u ccbt-bi-check.service -e --no-pager
```

### 5. 再起動して確認

```bash
sudo reboot
```

---

## ログの確認方法

### ファイルログ

```bash
# 最新のログを見る（latest.log は常に最新を指すシンボリックリンク）
cat /var/log/ccbt-bi-check/latest.log

# ログ一覧
ls -lt /var/log/ccbt-bi-check/

# 特定日時のログを見る
cat /var/log/ccbt-bi-check/check_20260302_120000.log
```

### journalctl（systemd ログ）

```bash
# 直近のチェック結果
journalctl -u ccbt-bi-check.service -e

# 今日のログだけ
journalctl -u ccbt-bi-check.service --since today

# リアルタイム監視
journalctl -u ccbt-bi-check.service -f
```

---

## カスタマイズ

### 環境変数で調整可能

| 変数 | デフォルト値 | 説明 |
|------|-------------|------|
| `CCBT_PROJECT_DIR` | `/home/m5stack/CCBT-2025-Parallel-Botanical-Garden-Proto` | プロジェクトのパス |
| `CCBT_LOG_DIR` | `/var/log/ccbt-bi-check` | ログ保存先 |
| `CCBT_CHECK_LANG` | `ja` | テスト言語 (`ja`, `en`, `zh`) |

サービスファイルの `Environment=` 行で変更できます。

### プロジェクトパスが異なる場合

`/etc/systemd/system/ccbt-bi-check.service` を編集:

```ini
Environment=CCBT_PROJECT_DIR=/path/to/your/project
ExecStart=/path/to/your/project/scripts/boot_check.sh
```

編集後に `sudo systemctl daemon-reload` を忘れずに。

### 特定チェックだけ実行したい場合

`boot_check.sh` 内の `uv run` の行を変更:

```bash
# LLM と TTS だけテスト
uv run python scripts/check_all.py --only llm,tts --lang "${CHECK_LANG}" 2>&1 | tee -a "${LOG_FILE}" || exit_code=$?

# LED をスキップ
uv run python scripts/check_all.py --skip-led --lang "${CHECK_LANG}" 2>&1 | tee -a "${LOG_FILE}" || exit_code=$?
```

### ログ保持数の変更

`boot_check.sh` 内の `MAX_LOG_FILES=30` を変更してください。

---

## 自動実行の無効化

```bash
# 起動時の自動実行を無効化
sudo systemctl disable ccbt-bi-check.service

# 手動実行は引き続き可能
sudo systemctl start ccbt-bi-check.service
```

---

## トラブルシューティング

### サービスが起動しない

```bash
# ステータス確認
sudo systemctl status ccbt-bi-check.service

# 詳細ログ
journalctl -u ccbt-bi-check.service -e --no-pager

# boot_check.sh を直接実行してエラーを確認
sudo -u m5stack /home/m5stack/CCBT-2025-Parallel-Botanical-Garden-Proto/scripts/boot_check.sh
```

### 依存サービスが起動する前にチェックが走る

`boot_check.sh` 内の `WAIT_SERVICES_TIMEOUT=120` を増やすか、`sleep 5` の値を調整してください。

### ユーザー名が m5stack ではない

サービスファイル内の `User=` / `Group=` と `Environment=CCBT_PROJECT_DIR=` を環境に合わせて修正してください。
