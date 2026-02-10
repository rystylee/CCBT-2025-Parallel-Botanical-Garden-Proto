import asyncio
import json
import os
import tempfile
from pathlib import Path

from loguru import logger
from openai import OpenAI

from api.utils import TTS_SETTINGS
from stackflow.utils import (
    close_tcp_connection,
    create_tcp_connection,
    parse_setup_response,
    receive_response,
    send_json,
)

# ========== Utility Functions for WAV File Generation & Playback ==========


def tts_generate_wav(text: str, model: str, output_path: str, api_url: str = "http://127.0.0.1:8000/v1") -> None:
    """
    Generate WAV file from text using OpenAI-compatible TTS API.

    Args:
        text: Text to synthesize
        model: TTS model name (e.g., "melotts-ja-jp")
        output_path: Output WAV file path
        api_url: StackFlow OpenAI-compatible API URL

    Raises:
        Exception: API request failed or file write failed
    """
    logger.debug(f"TTS API request to: {api_url}")
    logger.debug(f"Model: {model}, Input: {text[:50]}...")

    # Create OpenAI client with custom base_url
    client = OpenAI(api_key="sk-", base_url=api_url)

    # Generate speech using streaming response
    with client.audio.speech.with_streaming_response.create(
        model=model,
        response_format="wav",
        voice="",
        input=text,
    ) as response:
        response.stream_to_file(output_path)

    logger.info(f"WAV file generated: {output_path}")


async def ffmpeg_convert_for_tinyplay(
    input_path: str,
    output_path: str,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_format: str = "s16",
) -> None:
    """
    Convert WAV file for tinyplay compatibility using FFmpeg.

    Args:
        input_path: Input WAV file path
        output_path: Output WAV file path
        sample_rate: Target sample rate (Hz)
        channels: Target channel count (1: mono, 2: stereo)
        sample_format: Target sample format (s16, s32, etc.)

    Raises:
        RuntimeError: FFmpeg conversion failed
    """
    # Map sample format to FFmpeg format
    format_map = {
        "s16": "s16le",
        "s32": "s32le",
    }
    ffmpeg_format = format_map.get(sample_format, "s16le")

    cmd = [
        "ffmpeg",
        "-i",
        input_path,
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-sample_fmt",
        ffmpeg_format,
        "-y",  # Overwrite output file
        output_path,
    ]

    logger.debug(f"FFmpeg command: {' '.join(cmd)}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")
        logger.error(f"FFmpeg conversion failed: {error_msg}")
        raise RuntimeError(f"FFmpeg conversion failed: {error_msg}")

    logger.info(f"FFmpeg conversion completed: {output_path}")


async def ffmpeg_convert_for_tinyplay_with_rumble(
    input_path: str,
    output_path: str,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_format: str = "s16",
    rumble_freq: int = 50,
    rumble_gain: float = 0.1,
) -> None:
    """
    Convert WAV file with rumble effect using FFmpeg.

    Args:
        input_path: Input WAV file path
        output_path: Output WAV file path
        sample_rate: Target sample rate (Hz)
        channels: Target channel count (1: mono, 2: stereo)
        sample_format: Target sample format (s16, s32, etc.)
        rumble_freq: Rumble frequency (Hz)
        rumble_gain: Rumble gain (0.0-1.0)

    Raises:
        RuntimeError: FFmpeg conversion failed
    """
    format_map = {
        "s16": "s16le",
        "s32": "s32le",
    }
    ffmpeg_format = format_map.get(sample_format, "s16le")

    # Apply bass boost (rumble effect)
    filter_complex = f"bass=g={rumble_gain}:f={rumble_freq}:w=0.5"

    cmd = [
        "ffmpeg",
        "-i",
        input_path,
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-sample_fmt",
        ffmpeg_format,
        "-af",
        filter_complex,
        "-y",
        output_path,
    ]

    logger.debug(f"FFmpeg command (with rumble): {' '.join(cmd)}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")
        logger.error(f"FFmpeg conversion with rumble failed: {error_msg}")
        raise RuntimeError(f"FFmpeg conversion with rumble failed: {error_msg}")

    logger.info(f"FFmpeg conversion with rumble completed: {output_path}")


async def tinyplay_play(wav_path: str, card: int = 0, device: int = 1, timeout: int = 30) -> None:
    """
    Play WAV file using tinyplay command.

    Args:
        wav_path: WAV file path to play
        card: ALSA card number
        device: ALSA device number
        timeout: Playback timeout in seconds

    Raises:
        RuntimeError: tinyplay playback failed
    """
    cmd = ["tinyplay", wav_path, "-D", str(card), "-d", str(device)]

    logger.debug(f"tinyplay command: {' '.join(cmd)}")

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        logger.error(f"tinyplay playback timeout ({timeout}s)")
        raise RuntimeError(f"tinyplay playback timeout ({timeout}s)")

    if process.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")
        logger.error(f"tinyplay playback failed: {error_msg}")
        raise RuntimeError(f"tinyplay playback failed: {error_msg}")

    logger.info(f"tinyplay playback completed: {wav_path}")


# ==========================================================================


class StackFlowTTSClient:
    def __init__(self, config: dict):
        self.config = config
        self.set_params(config)

        self.sock = create_tcp_connection("localhost", 10001)
        self._init()

    def __del__(self):
        reset_date = self._create_reset_data()
        send_json(self.sock, reset_date)
        response = receive_response(self.sock)
        logger.debug(f"reset response: {response}")

        close_tcp_connection(self.sock)

    def set_params(self, config: dict):
        lang = config.get("common").get("lang")
        self.model = TTS_SETTINGS.get(lang).get("model")

        logger.info("[TTS info]")
        logger.info(f"lang: {lang}")
        logger.info(f"model: {self.model}")

    def speak(self, text: str) -> str:
        """
        Speak text directly through speaker (legacy method).

        Args:
            text: Text to synthesize

        Returns:
            str: Response from StackFlow
        """
        inference_date = self._create_inference_data(text)
        send_json(self.sock, inference_date)
        response = receive_response(self.sock, timeout=10.0)
        logger.debug(f"tts response: {response}")

        # reset_date = self._create_reset_data()
        # send_json(self.sock, reset_date)
        # response = receive_response(self.sock)
        # logger.debug(f"reset response: {response}")

    async def speak_to_file(self, text: str) -> None:
        """
        Generate WAV file from text and play it using tinyplay.

        This method uses OpenAI-compatible TTS API to generate WAV file,
        optionally converts it with FFmpeg, and plays it using tinyplay command.

        Args:
            text: Text to synthesize

        Raises:
            Exception: WAV generation, conversion, or playback failed
        """
        audio_config = self.config.get("audio", {})

        # Get configuration
        temp_wav_dir = audio_config.get("temp_wav_dir", "/tmp")
        enable_ffmpeg = audio_config.get("enable_ffmpeg_convert", True)
        enable_rumble = audio_config.get("enable_rumble_effect", False)
        sample_rate = audio_config.get("sample_rate", 16000)
        channels = audio_config.get("channels", 1)
        sample_format = audio_config.get("sample_format", "s16")
        tinyplay_card = audio_config.get("tinyplay_card", 0)
        tinyplay_device = audio_config.get("tinyplay_device", 1)

        # Ensure temp directory exists
        os.makedirs(temp_wav_dir, exist_ok=True)
        logger.debug(f"Using temp directory: {temp_wav_dir}")

        # Generate temporary file paths
        timestamp = asyncio.get_event_loop().time()
        raw_wav_path = os.path.join(temp_wav_dir, f"tts_raw_{timestamp}.wav")
        final_wav_path = os.path.join(temp_wav_dir, f"tts_final_{timestamp}.wav")

        try:
            # Step 1: Generate WAV file from TTS API
            logger.info(f"Generating WAV file: {text[:50]}...")
            await asyncio.to_thread(tts_generate_wav, text, self.model, raw_wav_path)

            # Step 2: Convert WAV file (optional)
            if enable_ffmpeg:
                logger.info("Converting WAV file with FFmpeg...")
                if enable_rumble:
                    rumble_freq = audio_config.get("rumble_freq", 50)
                    rumble_gain = audio_config.get("rumble_gain", 0.1)
                    await ffmpeg_convert_for_tinyplay_with_rumble(
                        raw_wav_path,
                        final_wav_path,
                        sample_rate,
                        channels,
                        sample_format,
                        rumble_freq,
                        rumble_gain,
                    )
                else:
                    await ffmpeg_convert_for_tinyplay(
                        raw_wav_path,
                        final_wav_path,
                        sample_rate,
                        channels,
                        sample_format,
                    )
                playback_path = final_wav_path
            else:
                playback_path = raw_wav_path

            # Step 3: Play WAV file using tinyplay
            logger.info("Playing WAV file with tinyplay...")
            await tinyplay_play(playback_path, tinyplay_card, tinyplay_device)

            logger.info("TTS playback completed successfully")

        except Exception as e:
            logger.error(f"TTS speak_to_file failed: {e}")
            raise

        finally:
            # Step 4: Cleanup temporary files
            for path in [raw_wav_path, final_wav_path]:
                if os.path.exists(path):
                    try:
                        os.remove(path)
                        logger.debug(f"Removed temporary file: {path}")
                    except Exception as e:
                        logger.warning(f"Failed to remove temporary file {path}: {e}")

    def _init(self):
        logger.info("Setup TTS...")

        audio_setup_data = self._create_audio_setup_data()
        sent_request_id = audio_setup_data["request_id"]
        send_json(self.sock, audio_setup_data)
        response = receive_response(self.sock)
        response_data = json.loads(response)
        self.audio_work_id = parse_setup_response(response_data, sent_request_id)
        logger.debug(f"audio setup response: {response_data}")

        tts_setup_data = self._create_tts_setup_data()
        sent_request_id = tts_setup_data["request_id"]
        send_json(self.sock, tts_setup_data)
        response = receive_response(self.sock)
        response_data = json.loads(response)
        self.tts_work_id = parse_setup_response(response_data, sent_request_id)
        logger.debug(f"tts setup response: {response}")
        logger.debug(f"tts_work_id: {self.tts_work_id}")

        logger.info("Setup TTS finished.")

    def _create_audio_setup_data(self) -> dict:
        return {
            "request_id": "audio_setup",
            "work_id": "audio",
            "action": "setup",
            "object": "audio.setup",
            "data": {
                "capcard": 0,
                "capdevice": 0,
                "capVolume": 0.5,
                "playcard": 0,
                "playdevice": 1,
                "playVolume": 0.15,
            },
        }

    def _create_tts_setup_data(self) -> dict:
        return {
            "request_id": "melotts_setup",
            "work_id": "melotts",
            "action": "setup",
            "object": "melotts.setup",
            "data": {
                "model": self.model,
                "response_format": "sys.pcm",
                "input": ["tts.utf-8.stream"],
                "enoutput": False,
                "enaudio": True,
            },
        }

    def _create_inference_data(self, text: str) -> dict:
        return {
            "request_id": "tts_inference",
            "work_id": self.tts_work_id,
            "action": "inference",
            "object": "tts.utf-8.stream",
            "data": {"delta": text, "index": 0, "finish": True},
        }

    def _create_reset_data(self) -> dict:
        return {"request_id": "4", "work_id": "sys", "action": "reset"}
