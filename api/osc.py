import asyncio
from typing import List

from loguru import logger
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

from api.llm import StackFlowLLMClient
from api.tts import StackFlowTTSClient


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
        server = AsyncIOOSCUDPServer(
            (self.ip_address, self.port),
            self.dispatcher,
            asyncio.get_event_loop()
        )
        logger.info(f"Serving on ip: {self.ip_address} port: {self.port}")
        self.transport, protocol = await server.create_serve_endpoint()

    def _print_message(self, address: str, *args: List[str]):
        logger.debug(f"address: {address}, args: {args}")


class OscClient:
    def __init__(
        self,
        config: dict
    ):
        self.config = config
        self.client_address: List[str] = config.get("osc").get("client_address")
        self.port = config.get("osc").get("send_port")

        self.clients = []
        for address in self.client_address:
            self.clients.append(SimpleUDPClient(address, self.port))

    def send(self, address, msg):
        for client in self.clients:
            client.send_message(address, msg)
        logger.info(f"sent the message. address: {address} msg: {msg}")
