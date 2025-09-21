import asyncio
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
        self.llm_client = StackFlowLLMClient(config)
        self.tts_client = StackFlowTTSClient(config)
        self.osc_server = OscServer(config)
        self.osc_client = OscClient(config)

        self._init()

    def _init(self):
        # self.osc_server.register_handler("/llm/process", func)
        # self.osc_server.register_handler("/llm/reload", func):
        # self.osc_server.register_handler("/tts/process", func):
        # self.osc_server.register_handler("/tts/reload", func):
        self.osc_server.register_handler("/process", self.process)

    def process(self, *args):
        logger.debug(args)
        output = self.llm_client.generate_text(args[0])
        logger.info(output)
        self.tts_client.speak(output)

        self.osc_client.send("/process", output)

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
