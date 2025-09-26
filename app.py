import asyncio
import subprocess
from loguru import logger

from api.llm import StackFlowLLMClient
from api.tts import StackFlowTTSClient
from api.osc import OscServer, OscClient

class AppController:
    def __init__(
        self,
        config: dict,
    ):
        logger.info("Initialize App Controller...")
        self.config = config
        logger.info(f"config: \n{config}")
        self.llm_client = StackFlowLLMClient(config)
        # self.tts_client = StackFlowTTSClient(config)
        self.osc_server = OscServer(config)
        self.osc_client = OscClient(config)

        self._init()

    def _init(self):
        self.osc_server.register_handler("/process", self.process_handler)
        self.osc_server.register_handler("/process/llm", self.process_llm_handler)
        self.osc_server.register_handler("/process/tts", self.process_tts)
        self.osc_server.register_handler("/reload/llm", self.reload_llm)
        self.osc_server.register_handler("/reload/tts", self.reload_tts)

    def process_handler(self, *args):
        asyncio.create_task(self.process(*args))

    def process_llm_handler(self, *args):
        asyncio.create_task(self.process_llm(*args))

    async def process(self, *args):
        logger.debug(f"process, args: {args}")
        output = await self.llm_client.generate_text(query=args[1])
        logger.info(f"llm output: \n{output}")
        self.tts_client.speak(output)

        self.osc_client.send("/process", output)

    async def process_llm(self, *args):
        logger.debug(f"pocess_llm, args: {args}")
        output = await self.llm_client.generate_text(query=args[1])
        logger.info(f"llm output: \n{output}")

        self.osc_client.send("/process/llm", output)

    def process_tts(self, *args):
        logger.debug(f"process_tts, args: {args}")
        self.tts_client.speak(text=args[1])

    def reload_llm(self, *args):
        """[TODO] Not implemented yet"""
        logger.debug(f"reload_llm, args: {args}")
        # subprocess.run("", shell=True)

    def reload_tts(self, *args):
        """[TODO] Not implemented yet"""
        logger.debug(f"reload_tts, args: {args}")
        # subprocess.run("", shell=True)

    async def run(self):
        logger.info("Starting App Controller")
        await self.osc_server.start_server()
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        except Exception as e:
            logger.error(f"Error: {e}")
