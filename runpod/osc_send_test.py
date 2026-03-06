#!/usr/bin/env python3
import os
import sys
from pythonosc.udp_client import SimpleUDPClient

TARGET_IP = os.getenv("OSC_TARGET_IP", "127.0.0.1")   # プログラム1が同じMacならこれでOK
TARGET_PORT = int(os.getenv("OSC_TARGET_PORT", "8000"))

text = " ".join(sys.argv[1:]).strip() or "こんにちは。これはテストです /mixer"
client = SimpleUDPClient(TARGET_IP, TARGET_PORT)
client.send_message("/mixer", text)

print(f"[SENT] /mixer '{text}' -> {TARGET_IP}:{TARGET_PORT}")
