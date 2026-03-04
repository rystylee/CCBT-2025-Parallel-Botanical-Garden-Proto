import asyncio
from typing import List, Optional

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

        # LED state tracking
        self._current_led_brightness = 0.0
        self._pulse_task: Optional[asyncio.Task] = None

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
        # Cancel pulse if running
        if self._pulse_task and not self._pulse_task.done():
            self._pulse_task.cancel()

    # ========== Phase implementations ==========

    async def _receiving_phase(self):
        """Phase 1: Receive input data for specified duration"""
        logger.info("RECEIVING phase started")
        receive_duration = self.config.get("cycle", {}).get("receive_duration", 3.0)
        await asyncio.sleep(receive_duration)

        logger.info(f"Buffer size: {len(self.input_buffer)}")
        self.state = "GENERATING"

    async def _generating_phase(self):
        """Phase 2: Generate text using LLM (LED pulses during wait)"""
        logger.info("GENERATING phase started")

        if not self.input_buffer:
            logger.warning("No input data, skipping generation")
            self.state = "RESTING"
            return

        led_config = self.config.get("led_control", {})
        waiting_max = led_config.get("waiting_max_brightness", 0.6)

        # Fade in from 0 to waiting_max, then start pulsing
        await self._led_fade(0.0, waiting_max)
        self._pulse_task = asyncio.create_task(self._led_pulse_loop())

        # Concatenate inputs in chronological order
        concatenated_text = self._concatenate_inputs()
        logger.info(f"Concatenated text: {concatenated_text}")

        # Generate 2-3 tokens with LLM
        try:
            sp_b64 = self.input_buffer[-1].soft_prefix_b64
            generated_text = await self.llm_client.generate_text(
                query=concatenated_text,
                lang=self.config.get("common", {}).get("lang", "ja"),
                soft_prefix_b64=sp_b64,
                soft_prefix_len=P,
            )
            self.generated_text = generated_text.replace("\n", " ").strip()
            self.tts_text = concatenated_text + generated_text.strip()
            logger.info(f"Generated text: {generated_text.strip()}")

            # Keep pulse running — it will continue during WAV preparation in OUTPUT phase
            self.state = "OUTPUT"

        except Exception as e:
            logger.error(f"Error in generation: {e}")
            # Stop pulsing, fade down, then rest
            await self._stop_pulse()
            await self._led_fade(self._current_led_brightness, 0.0)
            self.state = "RESTING"

    async def _output_phase(self):
        """Phase 3: Prepare WAV (while pulsing), then full brightness + immediate playback"""
        logger.info("OUTPUT phase started")

        # Skip output if buffer is empty
        if not self.input_buffer:
            logger.warning("Empty buffer in output phase, skipping output")
            await self._stop_pulse()
            await self._led_fade(self._current_led_brightness, 0.0)
            self.state = "RESTING"
            return

        # Step 1: Prepare WAV file while LED keeps pulsing
        #   prepare_wav_sync is blocking (TTS API + FFmpeg), so run in thread
        #   to let pulse_loop keep running on the event loop
        logger.info("Preparing WAV file (LED pulsing continues)...")
        wav_path = await asyncio.to_thread(self.tts_client.prepare_wav_sync, self.tts_text)

        # Step 2: Stop pulsing, fade up to full brightness
        await self._stop_pulse()

        if wav_path is None:
            logger.error("WAV preparation failed, skipping playback")
            await self._led_fade(self._current_led_brightness, 0.0)
            self.state = "RESTING"
            return

        await self._led_fade(self._current_led_brightness, 1.0)

        # Step 3: Play immediately (LED stays at max)
        try:
            await asyncio.to_thread(self.tts_client.play_wav_sync, wav_path)
        except Exception as e:
            logger.error(f"Error in TTS playback: {e}")

        # Step 4: Fade down after playback
        await self._led_fade(1.0, 0.0)

        # Step 5: Cleanup WAV file
        self.tts_client.cleanup_wav(wav_path)

        # Send generated text to target devices
        targets = self.config.get("targets", [])

        lowest_relay_count = min(data.relay_count for data in self.input_buffer)
        soft_prefix_b64 = self.input_buffer[-1].soft_prefix_b64
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

    # ========== Input handling ==========

    def _concatenate_inputs(self) -> str:
        """Concatenate input texts in received order"""
        return "".join([data.text for data in self.input_buffer])

    def add_input(self, text: str, soft_prefix_b64: str, relay_count: int):
        """Add input data to buffer with relay count filtering"""
        max_relay_count = self.config.get("cycle", {}).get("max_relay_count", 6)

        logger.debug(f"Relay count check: received={relay_count}, max_relay_count={max_relay_count}")

        if relay_count >= max_relay_count:
            logger.warning(
                f"Rejected data exceeding relay limit: relay_count={relay_count}, "
                f"max_relay_count={max_relay_count}, text='{text[:20]}...'"
            )
            return

        next_relay_count = relay_count + 1

        data = BIInputData(
            soft_prefix_b64=soft_prefix_b64,
            relay_count=next_relay_count,
            text=text.strip()
        )
        self.input_buffer.append(data)
        logger.info(
            f"Added input: '{text[:20]}...' relay_count={relay_count}->{next_relay_count} "
            f"soft_prefix_b64={soft_prefix_b64[:30]}... (buffer size: {len(self.input_buffer)})"
        )

    # ========== LED control ==========

    async def _led_fade(self, start: float, end: float, duration: float = None):
        """Fade LED from start brightness to end brightness.

        Uses fade_up_duration or fade_down_duration from config depending
        on direction, unless an explicit duration is given.
        Duration is scaled proportionally to the brightness range being covered.
        """
        led_config = self.config.get("led_control", {})
        if not led_config.get("enabled", False):
            return

        targets = led_config.get("targets", [])
        if not targets:
            return

        steps = led_config.get("fade_steps", 40)
        if duration is None:
            if end >= start:
                duration = led_config.get("fade_up_duration", 2.0)
            else:
                duration = led_config.get("fade_down_duration", 2.0)

        # Scale duration proportionally to the brightness range being covered
        full_range = abs(end - start)
        if full_range < 0.001:
            # Already at target, just send final value
            self._send_led(targets, end)
            self._current_led_brightness = end
            return

        scaled_duration = duration * full_range
        dt = scaled_duration / steps

        logger.info(f"LED fade: {start:.2f} -> {end:.2f} ({scaled_duration:.2f}s, {steps} steps)")

        for i in range(steps + 1):
            value = start + (end - start) * (i / steps)
            self._send_led(targets, value)
            self._current_led_brightness = value
            if i < steps:
                await asyncio.sleep(dt)

        logger.debug(f"LED fade complete: {end:.2f}")

    async def _led_pulse_loop(self):
        """Continuously pulse LED between waiting_min and waiting_max brightness.

        Runs until cancelled. Uses the same fade_steps / fade_up_duration /
        fade_down_duration as normal fades, scaled to the waiting brightness range.
        """
        led_config = self.config.get("led_control", {})
        if not led_config.get("enabled", False):
            return

        targets = led_config.get("targets", [])
        if not targets:
            return

        waiting_min = led_config.get("waiting_min_brightness", 0.2)
        waiting_max = led_config.get("waiting_max_brightness", 0.6)
        steps = led_config.get("fade_steps", 40)
        fade_up_duration = led_config.get("fade_up_duration", 2.0)
        fade_down_duration = led_config.get("fade_down_duration", 2.0)

        # Scale durations proportionally to the waiting brightness range
        brightness_range = waiting_max - waiting_min
        up_duration = fade_up_duration * brightness_range
        down_duration = fade_down_duration * brightness_range
        dt_up = up_duration / steps
        dt_down = down_duration / steps

        logger.info(
            f"LED pulse loop started: {waiting_min:.2f} <-> {waiting_max:.2f} "
            f"(up {up_duration:.2f}s, down {down_duration:.2f}s)"
        )

        try:
            while True:
                # Fade down: waiting_max -> waiting_min
                for i in range(steps + 1):
                    value = waiting_max - (waiting_max - waiting_min) * (i / steps)
                    self._send_led(targets, value)
                    self._current_led_brightness = value
                    if i < steps:
                        await asyncio.sleep(dt_down)

                # Fade up: waiting_min -> waiting_max
                for i in range(steps + 1):
                    value = waiting_min + (waiting_max - waiting_min) * (i / steps)
                    self._send_led(targets, value)
                    self._current_led_brightness = value
                    if i < steps:
                        await asyncio.sleep(dt_up)

        except asyncio.CancelledError:
            logger.debug(f"LED pulse loop cancelled at brightness {self._current_led_brightness:.2f}")
            raise

    async def _stop_pulse(self):
        """Cancel the pulse task if running and wait for clean shutdown."""
        if self._pulse_task is not None and not self._pulse_task.done():
            self._pulse_task.cancel()
            try:
                await self._pulse_task
            except asyncio.CancelledError:
                pass
        self._pulse_task = None

    def _send_led(self, targets: list, value: float):
        """Send LED brightness to all configured targets."""
        for target in targets:
            try:
                self.osc_client.send_to_target(target, "/led", value)
            except Exception as e:
                logger.error(f"Failed to send LED value to {target}: {e}")

    # ========== Status ==========

    def get_status(self) -> dict:
        """Get current status"""
        return {
            "state": self.state,
            "buffer_size": len(self.input_buffer),
            "generated_text": self.generated_text,
            "led_brightness": self._current_led_brightness,
        }
