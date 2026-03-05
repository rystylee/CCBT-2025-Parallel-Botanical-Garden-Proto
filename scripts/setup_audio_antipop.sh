#!/bin/bash
# ============================================================
# setup_audio_antipop.sh
# アンプポップノイズ防止: /etc/asound.conf + keepalive service
#
# 原因: ALSAドライバ (actt codec) が PCM open/close のたびに
#       pa_gpio->pa_speaker を 1→0 トグルし、アンプ電源断の
#       DC遷移がスピーカーに伝わりポップノイズが発生する
#
# 対策: dmixプラグインで仮想デバイスを作り、systemdサービスで
#       無音を流し続けることでALSAデバイスを常時openに保つ
# ============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Audio Anti-Pop Setup ==="

# --- 1. /etc/asound.conf を配置 ---
echo "[1/3] Installing /etc/asound.conf ..."

cat > /etc/asound.conf << 'ASOUND_EOF'
# CCBT Audio Anti-Pop Configuration
# dmixプラグインでソフトウェアミキシングし、ALSAデバイスを常時openに保つ
# これにより actt ドライバのアンプGPIOトグル (pa_speaker 1→0) を防止する

pcm.dmixer {
    type dmix
    ipc_key 1024
    ipc_perm 0666
    slave {
        pcm "hw:0,1"
        rate 32000
        format S16_LE
        channels 2
        period_size 1024
        buffer_size 4096
    }
}

pcm.!default {
    type plug
    slave.pcm "dmixer"
}

ctl.!default {
    type hw
    card 0
}
ASOUND_EOF

echo "  -> /etc/asound.conf installed"

# --- 2. systemd サービスを配置・有効化 ---
echo "[2/3] Installing ccbt-audio-keepalive.service ..."

cp "$PROJECT_DIR/systemd/ccbt-audio-keepalive.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable ccbt-audio-keepalive.service

echo "  -> Service installed and enabled"

# --- 3. サービス起動 ---
echo "[3/3] Starting ccbt-audio-keepalive.service ..."

systemctl start ccbt-audio-keepalive.service
sleep 1

if systemctl is-active --quiet ccbt-audio-keepalive.service; then
    echo "  -> Service is running"
else
    echo "  -> WARNING: Service failed to start. Check: journalctl -u ccbt-audio-keepalive"
    exit 1
fi

echo ""
echo "=== Setup complete ==="
echo "テスト: aplay -D dmixer /usr/local/m5stack/logo.wav"
echo "  -> 再生前後のポップノイズが消えていれば成功"
