"""
センサーOSC受信サーバー

大学の先生からOSC経由で送られるセンサーデータを受信し、
最新値をバッファに保持。マイクと同じサイクルで最新値をM5へ送信する。
"""
import asyncio
import time
from typing import Any, Dict, Optional

from loguru import logger
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer


class SensorDataBuffer:
    """各OSCアドレスの最新値とタイムスタンプを保持"""

    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}

    def update(self, address: str, *args):
        self._data[address] = {"values": list(args), "timestamp": time.time()}
        logger.debug(f"Sensor update: {address} = {args}")

    def get_latest(self, address: str, max_age: float = 30.0) -> Optional[Dict]:
        e = self._data.get(address)
        if e is None or time.time() - e["timestamp"] > max_age:
            return None
        return e

    def format_for_text(self, address: str, max_age: float = 30.0) -> str:
        """M5送信用テキスト形式"""
        e = self.get_latest(address, max_age)
        if e is None:
            return ""
        v = e["values"]
        return f"[sensor:{v[0]}]" if len(v) == 1 else f"[sensor:{','.join(str(x) for x in v)}]"

    def get_float_value(self, address: str, max_age: float = 30.0) -> Optional[float]:
        """0.0~1.0 float (soft prefix用)"""
        e = self.get_latest(address, max_age)
        if e is None or not e["values"]:
            return None
        try:
            return max(0.0, min(1.0, float(e["values"][0])))
        except (ValueError, TypeError):
            return None


class SensorOscReceiver:
    def __init__(self, port: int = 9001, listen_ip: str = "0.0.0.0"):
        self.port = port
        self.listen_ip = listen_ip
        self.buffer = SensorDataBuffer()
        self._dispatcher = Dispatcher()
        self._dispatcher.set_default_handler(self._handle)

    def _handle(self, address: str, *args):
        self.buffer.update(address, *args)

    def register_address(self, address: str):
        """明示登録 → 個別ログ出力"""
        def handler(addr, *args):
            self.buffer.update(addr, *args)
            logger.info(f"Sensor [{addr}]: {args}")
        self._dispatcher.map(address, handler)
        logger.info(f"Registered sensor address: {address}")

    async def start(self):
        server = AsyncIOOSCUDPServer(
            (self.listen_ip, self.port), self._dispatcher,
            asyncio.get_event_loop(),
        )
        transport, _ = await server.create_serve_endpoint()
        logger.info(f"Sensor OSC server on {self.listen_ip}:{self.port}")
        return transport
