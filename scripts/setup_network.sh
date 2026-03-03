#!/bin/bash
set -e

# --- 使い方: sudo ./setup_network.sh <IPの末尾番号> ---
# 例: sudo ./setup_network.sh 85  → 10.0.0.85 に設定

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

echo "=== M5Stack ネットワークセットアップ ==="
echo "IP: ${IP_ADDR}"
echo "Gateway: ${GATEWAY}"
echo "DNS: ${DNS}"
echo ""

# 1. /etc/network/interfaces を書き換え（バックアップ付き）
echo "[1/5] /etc/network/interfaces を設定中..."
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

# 2. DNS設定（systemd-resolved）
echo "[2/5] DNS設定（systemd-resolved）..."
mkdir -p /etc/systemd/resolved.conf.d/
cat > /etc/systemd/resolved.conf.d/dns.conf << EOF
[Resolve]
DNS=${DNS}
EOF

systemctl restart systemd-resolved
sleep 1
echo "  -> 完了"

# 3. ネットワーク再起動
echo "[3/5] ネットワーク再起動中..."
ifdown eth0 2>/dev/null || true
sleep 1
ifup eth0
sleep 2
echo "  -> 完了"

# 4. DNS反映
echo "[4/5] DNS設定を反映中..."
resolvconf -u
sleep 1
echo "  -> 完了"

# 5. 接続確認
echo "[5/5] 接続確認中..."
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
