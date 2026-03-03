#!/bin/bash
set -e

# --- 使い方: sudo ./setup_network.sh <IPの末尾番号> ---
# 例: sudo ./setup_network.sh 85  → 10.0.0.85 に設定、device_id を /etc/ccbt-device-id に保存

if [ -z "$1" ]; then
    echo "使い方: sudo $0 <IPの末尾番号 (1-254)>"
    echo "例: sudo $0 85"
    exit 1
fi

if [ "$EUID" -ne 0 ]; then
    echo "エラー: rootで実行してください (sudo)"
    exit 1
fi

IP_LAST="$1"

# バリデーション
if ! [[ "$IP_LAST" =~ ^[0-9]+$ ]] || [ "$IP_LAST" -lt 1 ] || [ "$IP_LAST" -gt 254 ]; then
    echo "エラー: 1-254 の数字を指定してください"
    exit 1
fi

IP_ADDR="10.0.0.${IP_LAST}"
GATEWAY="10.0.0.200"
DNS="8.8.8.8"
DEVICE_ID_FILE="/etc/ccbt-device-id"

echo "=== M5Stack ネットワークセットアップ ==="
echo "IP: ${IP_ADDR}"
echo "Gateway: ${GATEWAY}"
echo "DNS: ${DNS}"
echo "Device ID: ${IP_LAST}"
echo ""

# 1. /etc/network/interfaces を書き換え（バックアップ付き、再起動後の永続化用）
echo "[1/6] /etc/network/interfaces を設定中..."
cp /etc/network/interfaces /etc/network/interfaces.bak

cat > /etc/network/interfaces << EOF
# interfaces(5) file used by ifup(8) and ifdown(8)
# Include files from /etc/network/interfaces.d:
source /etc/network/interfaces.d/*

allow-hotplug eth0
#iface eth0 inet dhcp
iface eth0 inet static
    address ${IP_ADDR}
    netmask 255.255.255.0
    gateway ${GATEWAY}
    dns-nameservers ${DNS}
EOF

echo "  -> 完了（バックアップ: /etc/network/interfaces.bak）"

# 2. device_id を /etc/ccbt-device-id に保存
echo "[2/6] device_id を ${DEVICE_ID_FILE} に保存中..."
echo "${IP_LAST}" > "${DEVICE_ID_FILE}"
echo "  -> 完了"

# 3. DNS設定（systemd-resolved）
echo "[3/6] DNS設定（systemd-resolved）..."
mkdir -p /etc/systemd/resolved.conf.d/
cat > /etc/systemd/resolved.conf.d/dns.conf << EOF
[Resolve]
DNS=${DNS}
EOF

systemctl restart systemd-resolved
sleep 1
echo "  -> 完了"

# 4. ネットワーク即時反映（ipコマンドで直接設定）
echo "[4/6] ネットワーク設定を即時反映中..."
ip addr flush dev eth0
ip addr add ${IP_ADDR}/24 dev eth0
ip link set eth0 up
ip route add default via ${GATEWAY} 2>/dev/null || true
sleep 2
echo "  -> 完了"

# 5. DNS反映
echo "[5/6] DNS設定を反映中..."
resolvconf -u
sleep 1
echo "  -> 完了"

# 6. 接続確認
echo "[6/6] 接続確認中..."
echo ""

# ゲートウェイ
if ping -c 2 -W 3 ${GATEWAY} > /dev/null 2>&1; then
    echo "  ✓ ゲートウェイ (${GATEWAY}) OK"
else
    echo "  ✗ ゲートウェイ (${GATEWAY}) 到達不可"
fi

# インターネット
if ping -c 2 -W 3 8.8.8.8 > /dev/null 2>&1; then
    echo "  ✓ インターネット (8.8.8.8) OK"
else
    echo "  ✗ インターネット (8.8.8.8) 到達不可"
fi

# DNS名前解決
if ping -c 2 -W 3 github.com > /dev/null 2>&1; then
    echo "  ✓ DNS名前解決 (github.com) OK"
else
    echo "  ✗ DNS名前解決 (github.com) 失敗"
fi

# device_id 確認
if [ -f "${DEVICE_ID_FILE}" ]; then
    CURRENT_ID=$(cat "${DEVICE_ID_FILE}" | tr -d '[:space:]')
    if [ "${CURRENT_ID}" = "${IP_LAST}" ]; then
        echo "  ✓ device_id = ${CURRENT_ID} OK (${DEVICE_ID_FILE})"
    else
        echo "  ✗ device_id = ${CURRENT_ID}（期待値: ${IP_LAST}）"
    fi
fi

echo ""
echo "=== 設定内容 ==="
ip addr show eth0 | grep "inet "
ip route | grep default
grep nameserver /etc/resolv.conf | grep -v "^#"
echo ""
echo "=== 完了 ==="
echo ""
echo "=============================================="
echo "  ⚠  ゲートウェイ機 (10.0.0.200) の設定確認"
echo "=============================================="
echo ""
echo "M5Stackがインターネットに出るには、ゲートウェイ機"
echo "(10.0.0.200) でNAT設定が必要です。"
echo ""
echo "--- macOS の場合 （再起動で消えるので都度実行）---"
echo "  sudo sysctl -w net.inet.ip.forwarding=1"
echo "  echo \"nat on en0 from 10.0.0.0/24 to any -> (en0)\" | sudo pfctl -ef -"
echo "  ※ en0 はインターネット側のインタフェース名に置き換えること"
echo "  ※ 停止: sudo pfctl -d"
echo ""
echo "--- Ubuntu の場合 ---"
echo "  # IP転送を有効化（一時的）"
echo "  sudo sysctl -w net.ipv4.ip_forward=1"
echo ""
echo "  # IP転送を永続化"
echo "  echo 'net.ipv4.ip_forward=1' | sudo tee -a /etc/sysctl.conf"
echo "  sudo sysctl -p"
echo ""
echo "  # iptablesでNAT設定 ※ eth0 はインターネット側のインタフェース名に置き換えること"
echo "  sudo iptables -t nat -A POSTROUTING -s 10.0.0.0/24 -o eth0 -j MASQUERADE"
echo ""
echo "  # iptablesを永続化"
echo "  sudo apt install iptables-persistent -y"
echo "  sudo netfilter-persistent save"
echo ""
echo "=============================================="
