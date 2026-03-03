import asyncio
from typing import List

from loguru import logger

from api.llm import StackFlowLLMClient
from api.osc import OscClient
from api.tts import StackFlowTTSClient

from .models import BIInputData
from .utils import P


class BIController:
    """Controller for Botanical Intelligence cycle system"""

    def __init__(self, config: dict):
        logger.info("Initialize BI Controller...")
        self.config = config
        self.state = "STOPPED"
        self.input_buffer: List[BIInputData] = []
        self.generated_text = ""
        self.tts_text = ""

        # Initialize clients
        self.llm_client = StackFlowLLMClient(config)
        self.tts_client = StackFlowTTSClient(config)
        self.osc_client = OscClient(config)

        logger.info("BI Controller initialized")

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

        # LED fade up at the start of active processing
        await self._led_fade_up()

        # Concatenate inputs in chronological order
        concatenated_text = self._concatenate_inputs()
        logger.info(f"Concatenated text: {concatenated_text}")

        # Generate 2-3 tokens with LLM
        try:
            # Use soft_prefix_b64 from the latest input data
            sp_b64 = self.input_buffer[-1].soft_prefix_b64
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
            # Generation failed - fade down LED before resting
            await self._led_fade_down()
            self.state = "RESTING"

    async def _output_phase(self):
        """Phase 3: Play TTS and send output (LED is already on from generating phase)"""
        logger.info("OUTPUT phase started")

        # Skip output if buffer is empty
        if not self.input_buffer:
            logger.warning("Empty buffer in output phase, skipping output")
            await self._led_fade_down()
            self.state = "RESTING"
            return

        # Play TTS
        try:
            await self.tts_client.speak_to_file(self.tts_text)
        except Exception as e:
            logger.error(f"Error in TTS: {e}")

        # LED fade down after playback
        await self._led_fade_down()

        # Send generated text to target devices
        targets = self.config.get("targets", [])

        # Use the lowest relay_count and soft_prefix_b64 from buffer
        lowest_relay_count = min(data.relay_count for data in self.input_buffer)
        soft_prefix_b64 = self.input_buffer[-1].soft_prefix_b64  # Use latest soft prefix
        logger.debug(f"Using lowest relay_count from buffer: {lowest_relay_count}")

        try:
            self.osc_client.send_to_all_targets(
                targets, "/bi/input", self.generated_text, soft_prefix_b64, lowest_relay_count
            )
        except Exception as e:
            logger.error(f"Error sending to targets: {e}")

        # Send generated text to Mixer PC
        mixer_config = self.config.get("mixer")
        if mixer_config:
            try:
                mixer_target = {
                    "host": mixer_config.get("host"),
                    "port": mixer_config.get("port"),
                }
                self.osc_client.send_to_target(mixer_target, "/mixer", self.generated_text)
                logger.info(f"Sent to Mixer PC: {self.generated_text}")
            except Exception as e:
                logger.error(f"Error sending to Mixer PC: {e}")

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
        """Concatenate input texts in received order"""
        return "".join([data.text for data in self.input_buffer])

    def add_input(self, text: str, soft_prefix_b64: str, relay_count: int):
        """Add input data to buffer with relay count filtering"""
        max_relay_count = self.config.get("cycle", {}).get("max_relay_count", 6)

        # Enhanced logging for debugging relay count
        logger.debug(f"Relay count check: received={relay_count}, max_relay_count={max_relay_count}")

        # Check relay count immediately - reject data exceeding limit
        if relay_count >= max_relay_count:
            logger.warning(
                f"Rejected data exceeding relay limit: relay_count={relay_count}, "
                f"max_relay_count={max_relay_count}, text='{text[:20]}...'"
            )
            return

        # Increment relay count for next transmission
        next_relay_count = relay_count + 1

        data = BIInputData(soft_prefix_b64=soft_prefix_b64, relay_count=next_relay_count, text=text)
        self.input_buffer.append(data)
        logger.info(
            f"Added input: '{text[:20]}...' relay_count={relay_count}->{next_relay_count} "
            f"soft_prefix_b64={soft_prefix_b64[:30]}... (buffer size: {len(self.input_buffer)})"
        )

    async def _led_fade_up(self):
        """Fade LED up (0.0 -> 1.0) before TTS starts"""
        led_config = self.config.get("led_control", {})

        # Check if LED control is enabled
        if not led_config.get("enabled", False):
            logger.debug("LED control is disabled")
            return

        targets = led_config.get("targets", [])
        if not targets:
            logger.debug("No LED control targets configured")
            return

        steps = led_config.get("fade_steps", 40)
        duration = led_config.get("fade_up_duration", 2.0)
        dt = duration / steps

        logger.info(f"LED fade up: steps={steps}, duration={duration}s")

        # Send fade up messages to all targets
        for i in range(steps + 1):
            value = i / steps
            for target in targets:
                try:
                    self.osc_client.send_to_target(target, "/led", value)
                except Exception as e:
                    logger.error(f"Failed to send LED fade up to {target}: {e}")

            if i < steps:  # Don't sleep after the last step
                await asyncio.sleep(dt)

        logger.debug("LED fade up complete")

    async def _led_fade_down(self):
        """Fade LED down (1.0 -> 0.0) after TTS ends"""
        led_config = self.config.get("led_control", {})

        # Check if LED control is enabled
        if not led_config.get("enabled", False):
            logger.debug("LED control is disabled")
            return

        targets = led_config.get("targets", [])
        if not targets:
            logger.debug("No LED control targets configured")
            return

        steps = led_config.get("fade_steps", 40)
        duration = led_config.get("fade_down_duration", 2.0)
        dt = duration / steps

        logger.info(f"LED fade down: steps={steps}, duration={duration}s")

        # Send fade down messages to all targets
        for i in range(steps, -1, -1):
            value = i / steps
            for target in targets:
                try:
                    self.osc_client.send_to_target(target, "/led", value)
                except Exception as e:
                    logger.error(f"Failed to send LED fade down to {target}: {e}")

            if i > 0:  # Don't sleep after the last step
                await asyncio.sleep(dt)

        logger.debug("LED fade down complete")

    def get_status(self) -> dict:
        """Get current status"""
        return {
            "state": self.state,
            "buffer_size": len(self.input_buffer),
            "generated_text": self.generated_text,
        }
