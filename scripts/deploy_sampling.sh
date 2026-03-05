#!/bin/bash
# deploy_sampling.sh — v1.5.0 + soft_prefix + sampling バイナリ展開
# Usage: deploy_sampling.sh
set -e

BINARY_URL="https://www.dropbox.com/scl/fi/ccw4p2hxyjq3aiotxd7mp/llm_llm-1.8_v150sp?rlkey=ki2hrofyuv0mvjvnoluoy5jps&st=fz4kr4su&dl=1"
DEST=/opt/m5stack/bin/llm_llm-1.8
TS=$(date +%Y%m%d_%H%M%S)

echo "[1/5] backup binary"
if [ -f "$DEST" ]; then
    cp "$DEST" "${DEST}.bak_$TS"
fi

echo "[2/5] download new binary"
curl -fSL -o /tmp/llm_llm_new "$BINARY_URL"
chmod 755 /tmp/llm_llm_new

echo "[3/5] install binary"
install -m 755 /tmp/llm_llm_new "$DEST"
ln -sfn "$DEST" /opt/m5stack/bin/llm_llm
ln -sfn "$DEST" /opt/m5stack/bin/llm-llm
rm -f /tmp/llm_llm_new

echo "[4/5] fix libstdc++ (gcc-11 compat)"
LIBDIR=/usr/local/m5stack/lib/gcc-10.3
if [ -f "$LIBDIR/libstdc++.so.6" ] && [ ! -L "$LIBDIR/libstdc++.so.6" ]; then
    # real file -> rename and symlink to system
    mv "$LIBDIR/libstdc++.so.6" "$LIBDIR/libstdc++.so.6.old_gcc10"
    ln -sfn /usr/lib/aarch64-linux-gnu/libstdc++.so.6 "$LIBDIR/libstdc++.so.6"
    echo "  libstdc++ relinked"
elif [ -L "$LIBDIR/libstdc++.so.6" ]; then
    echo "  libstdc++ already symlink, OK"
else
    echo "  WARN: libstdc++ path not found, skipping"
fi

echo "[5/5] restart service"
systemctl restart llm-sys
sleep 3
if ss -lntp | grep -q ":10001"; then
    ldd "$DEST" | egrep "not found|GLIBCXX|CXXABI" && echo "WARN: lib issues" || echo "=== OK ==="
else
    echo "=== FAIL: llm-sys not listening ==="
fi
