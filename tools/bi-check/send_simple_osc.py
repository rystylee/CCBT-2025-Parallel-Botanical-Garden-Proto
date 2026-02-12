import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pythonosc import udp_client
import time

# クライアント作成
client = udp_client.SimpleUDPClient("10.0.0.1", 8000)

# 1. 入力データ送信
timestamp = time.time()
client.send_message("/bi/input", [timestamp, "こんにちは", "human", "ja"])
