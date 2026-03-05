#!/bin/bash
# ============================================================
# setup_audio_antipop.sh
# アンプポップノイズ防止: alsa-utils + /etc/asound.conf + keepalive
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

# --- 1. alsa-utils (aplay) のインストール ---
echo "[1/5] Checking aplay ..."

if command -v aplay &> /dev/null; then
    echo "  -> aplay already installed: $(which aplay)"
else
    echo "  -> aplay not found, installing alsa-utils ..."

    # apt では lib-llm バージョン不整合でブロックされるため
    # Dropbox 経由で arm64 .deb を直接取得・インストール
    DEB_DIR="/tmp/alsa-utils-debs"
    mkdir -p "$DEB_DIR"
    rm -f "$DEB_DIR"/*.deb

    curl -L --fail --retry 5 --retry-delay 5 -o "$DEB_DIR/libatopology2.deb" \
        "https://www.dropbox.com/scl/fi/lzmecw1h13a87gro6u7cv/libatopology2_1.2.6.1-1ubuntu1.1_arm64.deb?rlkey=df4hnzor1yp80kpd0zk3o1vpq&st=iqorzk1k&dl=1"

    curl -L --fail --retry 5 --retry-delay 5 -o "$DEB_DIR/libfftw3-single3.deb" \
        "https://www.dropbox.com/scl/fi/t1yi48rxmbk6c3j3xefit/libfftw3-single3_3.3.8-2ubuntu8_arm64.deb?rlkey=abxzv0w6sh97d5fp3ckhoolov&st=ncpre3xo&dl=1"

    curl -L --fail --retry 5 --retry-delay 5 -o "$DEB_DIR/alsa-utils.deb" \
        "https://www.dropbox.com/scl/fi/91hh9rydkpx3av3fcpxmb/alsa-utils_1.2.6-1ubuntu1_arm64.deb?rlkey=vv43p68scrikhm6vulwkd2xfm&st=x658nbrw&dl=1"

    dpkg -i "$DEB_DIR/libatopology2.deb" "$DEB_DIR/libfftw3-single3.deb" "$DEB_DIR/alsa-utils.deb"
    rm -rf "$DEB_DIR"

    if ! command -v aplay &> /dev/null; then
        echo "[ERROR] aplay のインストールに失敗しました"
        exit 1
    fi
    echo "  -> aplay installed: $(which aplay)"
fi

# --- 2. /etc/asound.conf を配置 ---
echo "[2/5] Installing /etc/asound.conf ..."

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

# --- 3. 既存サービスを停止（再セットアップ対応） ---
echo "[3/5] Stopping existing keepalive service (if any) ..."
systemctl stop ccbt-audio-keepalive.service 2>/dev/null || true

# --- 4. dmixer の動作確認 ---
echo "[4/5] Testing dmixer playback ..."

if [ -f /usr/local/m5stack/logo.wav ]; then
    if aplay -D dmixer /usr/local/m5stack/logo.wav 2>/dev/null; then
        echo "  -> dmixer playback OK"
    else
        echo "  -> WARNING: dmixer playback failed"
        echo "    /etc/asound.conf の設定を確認してください"
    fi
else
    echo "  -> SKIP: /usr/local/m5stack/logo.wav not found"
fi

# --- 5. systemd サービスを配置・有効化・起動 ---
echo "[5/5] Installing ccbt-audio-keepalive.service ..."

APLAY_PATH="$(which aplay)"

cat > /etc/systemd/system/ccbt-audio-keepalive.service << EOF
[Unit]
Description=CCBT Audio Keepalive - アンプポップノイズ防止
After=sound.target
Before=ccbt-bi-check.service

[Service]
Type=simple
ExecStart=${APLAY_PATH} -D dmixer -t raw -f S16_LE -r 32000 -c 2 -q /dev/zero
Restart=always
RestartSec=2
KillSignal=SIGTERM
TimeoutStopSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable ccbt-audio-keepalive.service
systemctl start ccbt-audio-keepalive.service
sleep 1

if systemctl is-active --quiet ccbt-audio-keepalive.service; then
    echo "  -> Service is running (ExecStart=${APLAY_PATH})"
else
    echo "  -> WARNING: Service failed to start"
    echo "    journalctl -u ccbt-audio-keepalive で確認してください"
    exit 1
fi

echo ""
echo "=== Setup complete ==="
echo "テスト: aplay -D dmixer /usr/local/m5stack/logo.wav"
echo "  -> 再生前後のポップノイズが消えていれば成功"
