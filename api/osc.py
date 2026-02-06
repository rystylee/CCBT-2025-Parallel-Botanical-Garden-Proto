import asyncio
from typing import List

from loguru import logger
from pythonosc import osc_message_builder
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient


class OscServer:
    def __init__(
        self,
        config: dict,
    ):
        self.config = config
        self.ip_address = config.get("network").get("ip_address")
        self.port = config.get("osc").get("receive_port")

        self.dispatcher = Dispatcher()
        self.register_handler("/*", self._print_message)

    def __del__(self):
        self.transport.close()

    def register_handler(self, address, func):
        self.dispatcher.map(address, func)

    async def start_server(self):
        server = AsyncIOOSCUDPServer((self.ip_address, self.port), self.dispatcher, asyncio.get_event_loop())
        logger.info(f"Serving on ip: {self.ip_address} port: {self.port}")
        self.transport, protocol = await server.create_serve_endpoint()

    def _print_message(self, address: str, *args: List[str]):
        logger.debug(f"address: {address}, args: {args}")


class OscClient:
    def __init__(self, config: dict):
        self.config = config
        self.port = config.get("osc").get("send_port")

    def send_to_target(self, target: dict, address: str, *args):
        """Send OSC message to a specific target device"""
        client = SimpleUDPClient(target["host"], target["port"])
        msg = osc_message_builder.OscMessageBuilder(address=address)
        for arg in args:
            msg.add_arg(arg)
        msg = msg.build()
        client.send(msg)
        logger.info(f"sent to target {target['host']}:{target['port']} " f"address: {address} msg: {msg}")

    def send_to_all_targets(self, targets: List[dict], address: str, *args):
        """Send OSC message to multiple target devices"""
        if not targets:
            logger.warning("No targets specified for OSC message")
            return

        for target in targets:
            try:
                self.send_to_target(target, address, *args)
            except Exception as e:
                logger.error(f"Failed to send OSC to {target['host']}:{target['port']}: {e}")
