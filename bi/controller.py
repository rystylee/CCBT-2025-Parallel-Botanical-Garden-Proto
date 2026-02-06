import asyncio
import time
from typing import List

from loguru import logger

from api.llm import StackFlowLLMClient
from api.osc import OscClient
from api.tts import StackFlowTTSClient

from .models import BIInputData
from .utils import P, make_random_soft_prefix_b64


class BIController:
    """Controller for Botanical Intelligence cycle system"""

    def __init__(self, config: dict):
        logger.info("Initialize BI Controller...")
        self.config = config
        self.state = "STOPPED"
        self.input_buffer: List[BIInputData] = []
        self.device_type = config.get("device", {}).get("type", "1st_BI")
        self.generated_text = ""
        self.tts_text = ""

        # Initialize clients
        self.llm_client = StackFlowLLMClient(config)
        self.tts_client = StackFlowTTSClient(config)
        self.osc_client = OscClient(config)

        logger.info(f"BI Controller initialized as {self.device_type}")

    async def start_cycle(self):
        """Start the BI cycle loop"""
        logger.info("Starting BI cycle")
        self.state = "RECEIVING"

        while self.state != "STOPPED":
            try:
                if self.state == "RECEIVING":
                    await self._receiving_phase()
                elif self.state == "GENERATING":
                    await self._generating_phase()
                elif self.state == "OUTPUT":
                    await self._output_phase()
                elif self.state == "RESTING":
                    await self._resting_phase()
            except Exception as e:
                logger.error(f"Error in BI cycle: {e}")
                await asyncio.sleep(1)

        logger.info("BI cycle stopped")

    def stop_cycle(self):
        """Stop the BI cycle"""
        logger.info("Stopping BI cycle")
        self.state = "STOPPED"

    async def _receiving_phase(self):
        """Phase 1: Receive input data for specified duration"""
        logger.info("RECEIVING phase started")
        receive_duration = self.config.get("cycle", {}).get("receive_duration", 3.0)
        await asyncio.sleep(receive_duration)

        # No longer need _filter_old_data() here - filtering is done in add_input()
        logger.info(f"Buffer size: {len(self.input_buffer)}")

        self.state = "GENERATING"

    async def _generating_phase(self):
        """Phase 2: Generate text using LLM"""
        logger.info("GENERATING phase started")

        if not self.input_buffer:
            logger.warning("No input data, skipping generation")
            self.state = "RESTING"
            return

        # Concatenate inputs in chronological order
        concatenated_text = self._concatenate_inputs()
        logger.info(f"Concatenated text: {concatenated_text}")

        # Generate 2-3 tokens with LLM
        try:
            sp_b64 = make_random_soft_prefix_b64()
            generated_text = await self.llm_client.generate_text(
                query=concatenated_text,
                lang=self.config.get("common", {}).get("lang", "ja"),
                soft_prefix_b64=sp_b64,
                soft_prefix_len=P,
            )
            self.generated_text = generated_text
            self.tts_text = concatenated_text + generated_text
            logger.info(f"Generated text: {generated_text}")
            self.state = "OUTPUT"
        except Exception as e:
            logger.error(f"Error in generation: {e}")
            self.state = "RESTING"

    async def _output_phase(self):
        """Phase 3: Send output and play TTS"""
        logger.info("OUTPUT phase started")

        # Skip output if buffer is empty
        if not self.input_buffer:
            logger.warning("Empty buffer in output phase, skipping output")
            self.state = "RESTING"
            return

        # Send generated text to target devices
        targets = self.config.get("targets", [])
        lang = self.config.get("common", {}).get("lang", "ja")

        # Use the newest timestamp from buffer
        newest_timestamp = max(data.timestamp for data in self.input_buffer)
        logger.debug(f"Using newest timestamp from buffer: {newest_timestamp}")

        try:
            self.osc_client.send_to_all_targets(
                targets, "/bi/input", newest_timestamp, self.generated_text, "BI", lang  # source_type
            )
        except Exception as e:
            logger.error(f"Error sending to targets: {e}")

        # Play TTS (all inputs + generated)
        try:
            self.tts_client.speak(self.tts_text)
        except Exception as e:
            logger.error(f"Error in TTS: {e}")

        # Clear buffer
        self.input_buffer.clear()
        self.state = "RESTING"

    async def _resting_phase(self):
        """Phase 4: Rest period"""
        logger.info("RESTING phase started")
        rest_duration = self.config.get("cycle", {}).get("rest_duration", 1.0)
        await asyncio.sleep(rest_duration)
        self.state = "RECEIVING"

    def _concatenate_inputs(self) -> str:
        """Concatenate input texts in chronological order"""
        sorted_data = sorted(self.input_buffer, key=lambda x: x.timestamp)
        return "".join([data.text for data in sorted_data])

    def add_input(self, timestamp: float, text: str, source_type: str, lang: str):
        """Add input data to buffer with immediate filtering"""
        current_time = time.time()
        max_age = self.config.get("cycle", {}).get("max_data_age", 60.0)

        # Check timestamp immediately - reject old data
        if (current_time - timestamp) > max_age:
            logger.warning(
                f"Rejected old data: timestamp={timestamp}, age={current_time - timestamp:.2f}s, "
                f"source={source_type}, text='{text[:20]}...'"
            )
            return

        # Filter by device type (2nd_BI ignores human input)
        if self.device_type == "2nd_BI" and source_type == "HUMAN":
            logger.debug(f"Filtered human input (2nd_BI mode): '{text[:20]}...'")
            return

        data = BIInputData(timestamp=timestamp, text=text, source_type=source_type, lang=lang)
        self.input_buffer.append(data)
        logger.info(f"Added input: {source_type} '{text[:20]}...' " f"(buffer size: {len(self.input_buffer)})")

    def get_status(self) -> dict:
        """Get current status"""
        return {
            "state": self.state,
            "device_type": self.device_type,
            "buffer_size": len(self.input_buffer),
            "generated_text": self.generated_text,
        }
