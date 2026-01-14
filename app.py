import asyncio
import subprocess
import base64
import struct
import random
from loguru import logger

from api.llm import StackFlowLLMClient
from api.tts import StackFlowTTSClient
from api.osc import OscServer, OscClient


P = 1    # num _prefix_token
H = 896  # tokens_embed_size
VALS = [0.0, 1e-4, 1e-3, 1e-2, 5e-2, 1e-1, 2e-1, 5e-1, 1.0, 2.0]


def f32_to_bf16_u16(x: float) -> int:
    """float32 -> bf16 (truncate) -> u16"""
    u32 = struct.unpack("<I", struct.pack("<f", x))[0]
    return (u32 >> 16) & 0xFFFF


def make_soft_prefix_b64_constant(P: int, H: int, val: float) -> str:
    """arrange bf16 little-endian u16 in P*H groups to create base64"""
    u16 = f32_to_bf16_u16(val)
    raw = struct.pack("<H", u16) * (P * H)
    return base64.b64encode(raw).decode("ascii")


def make_random_soft_prefix_b64() -> str:
    v = random.choice(VALS)
    logger.info(f"Selected soft prefix value: {v}")
    sp_b64 = make_soft_prefix_b64_constant(P, H, v)
    return sp_b64


class AppController:
    def __init__(
        self,
        config: dict,
    ):
        logger.info("Initialize App Controller...")
        self.config = config
        logger.info(f"config: \n{config}")
        self.llm_client = StackFlowLLMClient(config)
        self.tts_client = StackFlowTTSClient(config)
        self.osc_server = OscServer(config)
        self.osc_client = OscClient(config)

        self._init()

    def _init(self):
        self.osc_server.register_handler("/process", self.process_handler)
        self.osc_server.register_handler("/process/llm", self.process_llm_handler)
        self.osc_server.register_handler("/process/tts", self.process_tts)
        self.osc_server.register_handler("/reload/llm", self.reload_llm)
        self.osc_server.register_handler("/reload/tts", self.reload_tts)
        self.osc_server.register_handler("/ae/detect", self.ae_detect_handler)

    def process_handler(self, *args):
        asyncio.create_task(self.process(*args))

    def process_llm_handler(self, *args):
        asyncio.create_task(self.process_llm(*args))

    def ae_detect_handler(self, *args):
        asyncio.create_task(self.ae_detect(*args))

    async def process(self, *args):
        logger.debug(f"process, args: {args}")
        query = args[1]
        lang = args[2]
        sp_b64 = make_random_soft_prefix_b64()
        output = await self.llm_client.generate_text(query=query, lang=lang, soft_prefix_b64=sp_b64, soft_prefix_len=P)
        logger.info(f"llm output: \n{output}")
        self.osc_client.send("/process", output, self.llm_client.lang)

        self.tts_client.speak(output)

    async def process_llm(self, *args):
        logger.debug(f"pocess_llm, args: {args}")
        query = args[1]
        lang = args[2]
        sp_b64 = make_random_soft_prefix_b64()
        output = await self.llm_client.generate_text(query=query, lang=lang, soft_prefix_b64=sp_b64, soft_prefix_len=P)
        logger.info(f"llm output: \n{output}")
        self.osc_client.send("/process/llm", output, self.llm_client.lang)

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

    async def ae_detect(self, *args):
        logger.debug(f"ae_detect, args: {args}")
        query = self._get_random_input()
        lang = "en"
        sp_b64 = make_random_soft_prefix_b64()
        output = await self.llm_client.generate_text(query=query, lang=lang, soft_prefix_b64=sp_b64, soft_prefix_len=P)
        logger.info(f"llm output: \n{output}")
        self.osc_client.send("/process", output, self.llm_client.lang)

        self.tts_client.speak(output)

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

    def _get_random_input(self) -> str:
        return random.choice([
            "Beneath the silent sky",
            "When shadows learn to sing",
            "A single flame remembers",
            "In the hush of dawn",
            "Where rivers dream of light",
            "The wind carries forgotten names",
            "Between two heartbeats",
            "A door opens in the dark",
            "Stars whisper to the earth",
            "And still, the silence blooms",
        ]) 
