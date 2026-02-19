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

        # Play TTS (all inputs + generated) with status notifications
        try:
            # self.tts_client.speak(self.tts_text)
            await self.tts_client.speak_to_file(
                self.tts_text,
                on_start_callback=lambda text: self._send_tts_status("start", text),
                on_end_callback=lambda text, error=False: self._send_tts_status("end", text, error),
            )
        except Exception as e:
            logger.error(f"Error in TTS: {e}")

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
        """Concatenate input texts in chronological order"""
        sorted_data = sorted(self.input_buffer, key=lambda x: x.timestamp)
        return "".join([data.text for data in sorted_data])

    def add_input(self, timestamp: float, text: str, source_type: str, lang: str):
        """Add input data to buffer with immediate filtering"""
        current_time = time.time()
        max_age = self.config.get("cycle", {}).get("max_data_age", 60.0)
        age = current_time - timestamp

        # Enhanced logging for debugging timestamp issues
        logger.debug(
            f"Timestamp check: current={current_time:.2f}, received={timestamp:.2f}, "
            f"age={age:.2f}s, max_age={max_age}s"
        )

        # Check timestamp immediately - reject old data
        if age > max_age:
            logger.warning(
                f"Rejected old data: timestamp={timestamp}, age={age:.2f}s, "
                f"max_age={max_age}s, source={source_type}, text='{text[:20]}...'"
            )
            return

        # Also check for future timestamps (potential clock skew)
        if age < -5.0:  # Allow 5 seconds tolerance for network delay
            logger.warning(
                f"Rejected future data: timestamp={timestamp}, age={age:.2f}s, "
                f"source={source_type}, text='{text[:20]}...'"
            )
            return

        data = BIInputData(timestamp=timestamp, text=text, source_type=source_type, lang=lang)
        self.input_buffer.append(data)
        logger.info(
            f"Added input: {source_type} '{text[:20]}...' age={age:.2f}s " f"(buffer size: {len(self.input_buffer)})"
        )

    def _send_tts_status(self, status: str, text: str, error: bool = False):
        """
        Send TTS status notification via OSC.

        Args:
            status: "start" or "end"
            text: TTS text being spoken
            error: True if TTS failed (only for "end" status)
        """
        notification_config = self.config.get("tts_status_notifications", {})

        # Check if notifications are enabled
        if not notification_config.get("enabled", False):
            logger.debug("TTS status notifications are disabled")
            return

        targets = notification_config.get("targets", [])
        if not targets:
            logger.warning("No TTS status notification targets configured")
            return

        # Get device_id for the notification
        device_id = self.config.get("network", {}).get("device_id", 0)
        timestamp = time.time()
        send_simple = notification_config.get("send_simple_status", True)

        # Send to all configured targets
        for target in targets:
            try:
                target_dict = {"host": target.get("host"), "port": target.get("port")}

                # Select appropriate address based on status
                if status == "start":
                    address = target.get("start_address", "/bi/tts/start")
                    # Arguments: device_id, text, timestamp
                    self.osc_client.send_to_target(target_dict, address, device_id, text, timestamp)
                    logger.info(f"Sent TTS start notification to {target.get('name')}: device_id={device_id}")

                    # Send simple status: 1 (speaking)
                    if send_simple and target.get("simple_address"):
                        self.osc_client.send_to_target(target_dict, target.get("simple_address"), device_id, 1)
                        logger.debug(f"Sent simple TTS status to {target.get('name')}: 1 (speaking)")

                elif status == "end":
                    address = target.get("end_address", "/bi/tts/end")
                    # Arguments: device_id, timestamp, error (0 or 1)
                    error_flag = 1 if error else 0
                    self.osc_client.send_to_target(target_dict, address, device_id, timestamp, error_flag)
                    logger.info(
                        f"Sent TTS end notification to {target.get('name')}: "
                        f"device_id={device_id}, error={error_flag}"
                    )

                    # Send simple status: 0 (not speaking)
                    if send_simple and target.get("simple_address"):
                        self.osc_client.send_to_target(target_dict, target.get("simple_address"), device_id, 0)
                        logger.debug(f"Sent simple TTS status to {target.get('name')}: 0 (not speaking)")

            except Exception as e:
                logger.error(f"Failed to send TTS status to {target.get('name')}: {e}")

    def get_status(self) -> dict:
        """Get current status"""
        return {
            "state": self.state,
            "buffer_size": len(self.input_buffer),
            "generated_text": self.generated_text,
        }
