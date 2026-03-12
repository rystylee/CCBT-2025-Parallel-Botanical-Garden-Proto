import asyncio
import os
import subprocess
from pathlib import Path
from typing import List, Optional

from loguru import logger

from api.llm import StackFlowLLMClient
from api.osc import OscClient
from api.tts import StackFlowTTSClient

from .models import BIInputData
from .utils import P, override_soft_prefix_val
from api.utils import cleanup_ng_words


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
        self._led_lock = asyncio.Lock()  # Prevents concurrent LED control

        # Waiting audio loop
        self._waiting_proc: Optional[subprocess.Popen] = None
        self._waiting_loop_task: Optional[asyncio.Task] = None

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
        # Kill waiting audio if running
        if self._waiting_proc is not None:
            try:
                self._waiting_proc.kill()
            except Exception:
                pass
        if self._waiting_loop_task and not self._waiting_loop_task.done():
            self._waiting_loop_task.cancel()

    # ========== Phase implementations ==========

    async def _receiving_phase(self):
        """Phase 1: Receive input data for specified duration"""
        logger.info("RECEIVING phase started")

        # Start LED pulsing for RECEIVING state
        led_config = self.config.get("led_control", {})
        receiving_min = led_config.get("receiving_min_brightness", 0.0)
        receiving_max = led_config.get("receiving_max_brightness", 0.1)

        # Start pulsing immediately with RECEIVING-specific brightness range
        logger.info(f"LED pulse loop starting for RECEIVING: {receiving_min:.2f} <-> {receiving_max:.2f}")
        await self._start_pulse(min_brightness=receiving_min, max_brightness=receiving_max)

        # Start waiting audio loop
        await self._start_waiting_loop()

        receive_duration = self.config.get("cycle", {}).get("receive_duration", 3.0)
        await asyncio.sleep(receive_duration)

        # Stop pulsing before moving to GENERATING
        logger.info("Stopping LED pulse for RECEIVING phase")
        await self._stop_pulse()

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
        await self._start_pulse()

        # Concatenate inputs in chronological order
        concatenated_text = self._concatenate_inputs()
        logger.info(f"Concatenated text: {concatenated_text}")

        # Generate 2-3 tokens with LLM
        try:
            sp_b64 = override_soft_prefix_val(self.input_buffer[-1].soft_prefix_b64, self.config)
            generated_text = await self.llm_client.generate_text(
                query=concatenated_text,
                soft_prefix_b64=sp_b64,
                soft_prefix_len=P,
            )
            cleaned = cleanup_ng_words(generated_text)
            self.generated_text = cleaned
            self.tts_text = cleaned
            logger.info(f"Generated text: {generated_text.strip()}")
            logger.info(f"Cleaned text: {self.tts_text}")

            # Keep pulse running — it will continue during WAV preparation in OUTPUT phase
            self.state = "OUTPUT"

        except Exception as e:
            logger.error(f"Error in generation: {e}")
            # Stop waiting audio, pulsing, fade down, then rest
            await self._stop_waiting_loop()
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
        logger.info("Preparing WAV file (LED pulsing continues)...")
        wav_path = await asyncio.to_thread(self.tts_client.prepare_wav_sync, self.tts_text)

        # Step 2: Stop LED pulsing
        await self._stop_pulse()

        # If WAV preparation succeeded, play it with LED animation
        if wav_path is not None:
            # Step 3: Start generated WAV playback first (non-blocking)
            playback_proc = await asyncio.to_thread(self.tts_client.start_playback, wav_path)

            # Step 4: Stop waiting audio (brief crossfade overlap via dmix)
            await self._stop_waiting_loop()

            # Step 5: Fade up LED concurrently with playback
            await self._led_fade(self._current_led_brightness, 1.0)

            # Step 6: Wait for playback to finish
            try:
                ret = await asyncio.to_thread(playback_proc.wait)
                if ret != 0:
                    stderr = (
                        playback_proc.stderr.read().decode(errors="replace").strip() if playback_proc.stderr else ""
                    )
                    logger.error(f"TTS playback failed (rc={ret}): {stderr}")
            except Exception as e:
                logger.error(f"Error in TTS playback: {e}")

            # Step 7: Fade down after playback
            await self._led_fade(1.0, 0.0)

            # Step 8: Cleanup WAV file
            self.tts_client.cleanup_wav(wav_path)
        else:
            logger.error("WAV preparation failed, skipping playback but continuing to send message")
            await self._stop_waiting_loop()
            await self._led_fade(self._current_led_brightness, 0.0)

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

        data = BIInputData(soft_prefix_b64=soft_prefix_b64, relay_count=next_relay_count, text=text.strip())
        self.input_buffer.append(data)
        logger.info(
            f"Added input: '{text[:20]}...' relay_count={relay_count}->{next_relay_count} "
            f"soft_prefix_b64={soft_prefix_b64[:30]}... (buffer size: {len(self.input_buffer)})"
        )

    # ========== Waiting audio loop ==========

    async def _start_waiting_loop(self):
        """Start looping waiting audio in background."""
        # Don't start if already running
        if self._waiting_loop_task is not None and not self._waiting_loop_task.done():
            return

        audio_config = self.config.get("audio", {})
        playback_device = audio_config.get("playback_device", "")
        waiting_dir = audio_config.get("waiting_audio_dir", "audio")

        # Per-device prefix selection based on last digit of device_id
        device_id = audio_config.get("device_id", 0)
        alt_digits = audio_config.get("waiting_audio_alt_digits", [])
        if (device_id % 10) in alt_digits:
            waiting_prefix = audio_config.get("waiting_audio_alt_prefix", "CF_")
            logger.info(f"Device {device_id} (last digit {device_id % 10}) -> alt waiting prefix: {waiting_prefix}")
        else:
            waiting_prefix = audio_config.get("waiting_audio_prefix", "waiting_")

        # Collect matching files
        import glob

        patterns = [
            os.path.join(waiting_dir, f"{waiting_prefix}*.wav"),
            os.path.join(waiting_dir, f"{waiting_prefix}*.mp3"),
        ]
        files = []
        for pat in patterns:
            files.extend(glob.glob(pat))
        files.sort()

        if not files:
            logger.warning(f"No waiting audio files found: {waiting_dir}/{waiting_prefix}*")
            return

        # Ensure all files match dmixer format (48000Hz, 2ch, s16)
        target_sr = audio_config.get("sample_rate", 48000)
        target_ch = audio_config.get("channels", 2)
        target_fmt = audio_config.get("sample_format", "s16")
        files = await asyncio.to_thread(
            self._ensure_waiting_audio_format,
            files,
            target_sr,
            target_ch,
            target_fmt,
        )

        if not files:
            logger.warning("No valid waiting audio files after format conversion")
            return

        logger.info(f"Starting waiting audio loop: {len(files)} files " f"in {waiting_dir}/ prefix={waiting_prefix}")
        self._waiting_loop_task = asyncio.create_task(self._waiting_loop(files, playback_device))

    def _ensure_waiting_audio_format(
        self,
        files: list,
        sample_rate: int,
        channels: int,
        sample_format: str,
    ) -> list:
        """Convert waiting audio files to dmixer-compatible format if needed.

        Checks WAV header (sample rate, channels, bit depth).
        Files that don't match are converted in-place via FFmpeg.
        Non-WAV files (mp3 etc.) are always converted to .wav.
        Returns list of playable file paths.
        """
        import struct
        import wave

        playable = []
        for path in files:
            try:
                needs_convert = False

                # Non-WAV files always need conversion
                if not path.lower().endswith(".wav"):
                    needs_convert = True
                else:
                    # Check WAV header
                    try:
                        with wave.open(path, "rb") as wf:
                            if (
                                wf.getframerate() != sample_rate
                                or wf.getnchannels() != channels
                                or wf.getsampwidth() != (16 if sample_format == "s16" else 32) // 8
                            ):
                                needs_convert = True
                    except Exception:
                        needs_convert = True

                if needs_convert:
                    out_path = path.rsplit(".", 1)[0] + ".wav"
                    tmp_path = out_path + ".tmp.wav"
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        path,
                        "-ar",
                        str(sample_rate),
                        "-ac",
                        str(channels),
                        "-sample_fmt",
                        sample_format,
                        tmp_path,
                    ]
                    logger.info(f"Converting waiting audio: {path} -> {sample_rate}Hz/{channels}ch/{sample_format}")
                    subprocess.run(cmd, check=True, capture_output=True, text=True)
                    os.replace(tmp_path, out_path)
                    playable.append(out_path)
                else:
                    playable.append(path)

            except Exception as e:
                logger.warning(f"Failed to prepare waiting audio {path}: {e}")

        return playable

    async def _waiting_loop(self, files: list, playback_device: str):
        """Keep playing random waiting audio until cancelled."""
        import random

        try:
            while True:
                path = random.choice(files)
                if playback_device:
                    cmd = ["aplay", "-D", playback_device, str(path)]
                else:
                    card = self.config.get("audio", {}).get("tinyplay_card", 0)
                    device = self.config.get("audio", {}).get("tinyplay_device", 1)
                    cmd = ["tinyplay", f"-D{card}", f"-d{device}", str(path)]

                logger.debug(f"Waiting audio play: {' '.join(cmd)}")
                proc = await asyncio.to_thread(
                    lambda: subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                )
                self._waiting_proc = proc
                ret = await asyncio.to_thread(proc.wait)
                self._waiting_proc = None

                if ret != 0:
                    stderr = proc.stderr.read().decode(errors="replace").strip()
                    logger.warning(f"Waiting audio playback failed (rc={ret}): {stderr}")
                    await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            logger.debug("Waiting audio loop cancelled")
            raise

    async def _stop_waiting_loop(self):
        """Stop the waiting audio loop and wait for clean shutdown."""
        if self._waiting_loop_task is None or self._waiting_loop_task.done():
            self._waiting_proc = None
            self._waiting_loop_task = None
            return

        # Cancel the loop task
        self._waiting_loop_task.cancel()

        # Kill the currently playing process immediately
        if self._waiting_proc is not None:
            try:
                self._waiting_proc.terminate()
                await asyncio.to_thread(self._waiting_proc.wait)
            except Exception:
                try:
                    self._waiting_proc.kill()
                except Exception:
                    pass
            self._waiting_proc = None

        # Wait for the task to finish
        try:
            await self._waiting_loop_task
        except asyncio.CancelledError:
            pass
        self._waiting_loop_task = None
        logger.info("Waiting audio loop stopped")

    # ========== LED control ==========


    async def set_bri_ex(self, value: float):
        """Set bri_ex (external brightness) on the LED server.

        Args:
            value: Brightness 0.0-1.0
        """
        led_config = self.config.get("led_control", {})
        if not led_config.get("enabled", False):
            return
        targets = led_config.get("targets", [])
        if targets:
            await self._send_bri_ex(targets, value)

    async def set_led_ratio(self, value: float):
        """Set led_ratio on the LED server.

        Args:
            value: 0.0-1.0 (1.0 = bri only, 0.0 = bri_ex only)
        """
        led_config = self.config.get("led_control", {})
        if not led_config.get("enabled", False):
            return
        targets = led_config.get("targets", [])
        if targets:
            await self._send_led_ratio(targets, value)

    async def start_soft_prefix_led_performance(self, fade_up_duration: float, fade_down_duration: float):
        """Execute LED performance for soft prefix update event.

        Temporarily suspends any running pulse task, performs a fade animation
        (0.0 -> 1.0 -> 0.0), and then resumes the previous pulse task based on
        the current phase state.

        Args:
            fade_up_duration: Duration in seconds for fade up (0.0 -> 1.0)
            fade_down_duration: Duration in seconds for fade down (1.0 -> 0.0)
        """
        logger.info(f"Soft prefix LED performance starting: up={fade_up_duration}s, down={fade_down_duration}s")

        # Save current state to resume later
        suspended_state = None
        suspended_min_brightness = None
        suspended_max_brightness = None

        # Suspend current pulse task if running
        if self._pulse_task is not None and not self._pulse_task.done():
            suspended_state = self.state

            # Save brightness range for the suspended task
            led_config = self.config.get("led_control", {})
            if suspended_state == "RECEIVING":
                suspended_min_brightness = led_config.get("receiving_min_brightness", 0.0)
                suspended_max_brightness = led_config.get("receiving_max_brightness", 0.1)
            elif suspended_state == "GENERATING":
                suspended_min_brightness = led_config.get("generating_min_brightness", 0.05)
                suspended_max_brightness = led_config.get("generating_max_brightness", 0.25)

            logger.debug(f"Suspending pulse task in {suspended_state} phase")
            await self._stop_pulse()

        try:
            # Perform fade up: current -> 1.0
            await self._led_fade(self._current_led_brightness, 1.0, duration=fade_up_duration)

            # Perform fade down: 1.0 -> 0.0
            await self._led_fade(1.0, 0.0, duration=fade_down_duration)

        finally:
            # Resume the pulse task if it was running
            if suspended_state in ["RECEIVING", "GENERATING"]:
                logger.debug(
                    f"Resuming {suspended_state} pulse: {suspended_min_brightness} <-> {suspended_max_brightness}"
                )
                await self._start_pulse(
                    min_brightness=suspended_min_brightness, max_brightness=suspended_max_brightness
                )

            logger.info("Soft prefix LED performance complete")

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
            await self._send_led(targets, end)
            self._current_led_brightness = end
            return

        scaled_duration = duration * full_range
        dt = scaled_duration / steps

        logger.info(f"LED fade: {start:.2f} -> {end:.2f} ({scaled_duration:.2f}s, {steps} steps)")

        for i in range(steps + 1):
            value = start + (end - start) * (i / steps)
            await self._send_led(targets, value)
            self._current_led_brightness = value
            if i < steps:
                await asyncio.sleep(dt)

        logger.debug(f"LED fade complete: {end:.2f}")

    async def _led_pulse_loop(self, min_brightness=None, max_brightness=None):
        """Continuously pulse LED between min and max brightness.

        Runs until cancelled. Uses the same fade_steps / fade_up_duration /
        fade_down_duration as normal fades, scaled to the brightness range.

        Args:
            min_brightness: Minimum brightness (0.0-1.0). If None, uses waiting_min_brightness from config.
            max_brightness: Maximum brightness (0.0-1.0). If None, uses waiting_max_brightness from config.
        """
        led_config = self.config.get("led_control", {})
        if not led_config.get("enabled", False):
            return

        targets = led_config.get("targets", [])
        if not targets:
            return

        # Use parameters or fall back to generating_ config (for GENERATING phase)
        if min_brightness is None:
            min_brightness = led_config.get("generating_min_brightness", 0.2)
        if max_brightness is None:
            max_brightness = led_config.get("generating_max_brightness", 0.6)

        waiting_min = min_brightness
        waiting_max = max_brightness
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
                    await self._send_led(targets, value)
                    self._current_led_brightness = value
                    if i < steps:
                        await asyncio.sleep(dt_down)

                # Fade up: waiting_min -> waiting_max
                for i in range(steps + 1):
                    value = waiting_min + (waiting_max - waiting_min) * (i / steps)
                    await self._send_led(targets, value)
                    self._current_led_brightness = value
                    if i < steps:
                        await asyncio.sleep(dt_up)

        except asyncio.CancelledError:
            logger.debug(f"LED pulse loop cancelled at brightness {self._current_led_brightness:.2f}")
            raise

    async def _start_pulse(self, min_brightness=None, max_brightness=None):
        """Start pulse loop, ensuring previous one is stopped first.

        This helper prevents task leaks by guaranteeing that any existing
        pulse task is cancelled before starting a new one.

        Args:
            min_brightness: Minimum brightness (0.0-1.0). If None, uses waiting_min_brightness from config.
            max_brightness: Maximum brightness (0.0-1.0). If None, uses waiting_max_brightness from config.
        """
        await self._stop_pulse()  # Ensure old task is stopped
        self._pulse_task = asyncio.create_task(
            self._led_pulse_loop(min_brightness=min_brightness, max_brightness=max_brightness)
        )

    async def _stop_pulse(self):
        """Cancel the pulse task if running and wait for clean shutdown."""
        if self._pulse_task is not None and not self._pulse_task.done():
            logger.debug(f"Stopping pulse task: {id(self._pulse_task)}")
            self._pulse_task.cancel()
            try:
                await self._pulse_task
            except asyncio.CancelledError:
                pass
            finally:
                self._pulse_task = None
        else:
            self._pulse_task = None

    async def _send_led(self, targets: list, value: float):
        """Send LED brightness to all configured targets with exclusive lock."""
        async with self._led_lock:
            for target in targets:
                try:
                    self.osc_client.send_to_target(target, "/led", value)
                except Exception as e:
                    logger.error(f"Failed to send LED value to {target}: {e}")

    async def _send_bri_ex(self, targets: list, value: float):
        """Send bri_ex (external brightness) to all configured LED targets."""
        async with self._led_lock:
            for target in targets:
                try:
                    self.osc_client.send_to_target(target, "/bri_ex", value)
                except Exception as e:
                    logger.error(f"Failed to send bri_ex to {target}: {e}")

    async def _send_led_ratio(self, targets: list, value: float):
        """Send led_ratio to all configured LED targets.

        led_ratio controls the mix between bri and bri_ex:
          duty = (led_ratio * bri) + ((1 - led_ratio) * bri_ex)
          1.0 = bri only (default), 0.0 = bri_ex only
        """
        async with self._led_lock:
            for target in targets:
                try:
                    self.osc_client.send_to_target(target, "/led_ratio", value)
                except Exception as e:
                    logger.error(f"Failed to send led_ratio to {target}: {e}")

    # ========== Status ==========

    def get_status(self) -> dict:
        """Get current status"""
        return {
            "state": self.state,
            "buffer_size": len(self.input_buffer),
            "generated_text": self.generated_text,
            "led_brightness": self._current_led_brightness,
        }
