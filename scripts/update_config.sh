#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'EOF'
使い方:
  update_config.sh --ip <IP> --lang <LANG> [--file config.json] [--clients "IP1,IP2,..."]

必須:
  --ip <IP>            .network.ip_address に設定するIP
  --lang <LANG>        .common.lang に設定する言語コード (例: en, ja, zh)

任意:
  --file <PATH>        対象のconfig.json (既定: .config/config.json)
  --clients "<CSV>"    カンマ区切りのクライアントIP群 (例: "192.168.151.99,192.168.151.100")
  -h, --help           このヘルプを表示

メモ:
  client_address は指定されたリストで常に「置き換え」られます。
  未指定の場合は空配列になります。
  jq が必要です: https://stedolan.github.io/jq/
EOF
}

CONFIG_FILE="config/config.json"
IP_ADDRESS=""
LANG=""
CLIENTS=""

# 引数パース
while (( "$#" )); do
  case "$1" in
    --ip) IP_ADDRESS="${2:-}"; shift 2 ;;
    --lang) LANG="${2:-}"; shift 2 ;;
    --file) CONFIG_FILE="${2:-}"; shift 2 ;;
    --clients) CLIENTS="${2:-}"; shift 2 ;;
    -h|--help) show_help; exit 0 ;;
    --) shift; break ;;
    -*) echo "不明なオプション: $1" >&2; show_help; exit 2 ;;
    *) echo "位置引数は不要です: $1" >&2; show_help; exit 2 ;;
  esac
done

# 前提チェック
command -v jq >/dev/null 2>&1 || { echo "エラー: jq が見つかりません。"; exit 1; }
[[ -f "$CONFIG_FILE" ]] || { echo "エラー: ファイルが見つかりません: $CONFIG_FILE"; exit 1; }
[[ -n "$IP_ADDRESS" ]] || { echo "エラー: --ip は必須です。"; show_help; exit 1; }
[[ -n "$LANG" ]] || { echo "エラー: --lang は必須です。"; show_help; exit 1; }

# client配列作成（空の場合は空配列）
CLIENT_ARRAY="[]"
if [[ -n "$CLIENTS" ]]; then
  CLIENT_ARRAY=$(echo "$CLIENTS" | awk -F',' '{for(i=1;i<=NF;i++) print "\""$i"\""}' | paste -sd "," -)
  CLIENT_ARRAY="[$CLIENT_ARRAY]"
fi

# バックアップ作成（タイムスタンプ付き）
ts=$(date +%Y%m%d-%H%M%S)
cp -p "$CONFIG_FILE" "${CONFIG_FILE}.bak.${ts}"

# jqで更新（整形出力付き）
jq -M \
  --arg ip "$IP_ADDRESS" \
  --arg lang "$LANG" \
  --argjson clients "$CLIENT_ARRAY" \
  '
    .network.ip_address = $ip
    | .osc.client_address = $clients
    | .common.lang = $lang
  ' "$CONFIG_FILE" > "${CONFIG_FILE}.tmp"

mv "${CONFIG_FILE}.tmp" "$CONFIG_FILE"
echo "更新完了: $CONFIG_FILE"
