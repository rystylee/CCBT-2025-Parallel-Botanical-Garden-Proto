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


def ffmpeg_convert_for_tinyplay(
    input_path: str,
    output_path: str,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_format: str = "s16",
    quiet: bool = True,
) -> None:
    """
    Convert WAV file for tinyplay compatibility using FFmpeg.

    Args:
        input_path: Input WAV file path
        output_path: Output WAV file path
        sample_rate: Target sample rate (Hz)
        channels: Target channel count (1: mono, 2: stereo)
        sample_format: Target sample format (s16, s32, etc.)
        quiet: Suppress FFmpeg output (default: True)

    Raises:
        RuntimeError: FFmpeg conversion failed
    """
    import subprocess

    cmd = ["ffmpeg", "-y"]
    if quiet:
        cmd += ["-hide_banner", "-loglevel", "error"]
    cmd += [
        "-i",
        str(input_path),
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-sample_fmt",
        sample_format,
        str(output_path),
    ]

    logger.debug(f"FFmpeg command: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"FFmpeg conversion completed: {output_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg conversion failed: {e.stderr}")
        raise RuntimeError(f"FFmpeg conversion failed: {e.stderr}")


def ffmpeg_convert_for_tinyplay_with_rumble(
    input_path: str,
    output_path: str,
    sample_rate: int = 16000,
    channels: int = 1,
    sample_format: str = "s16",
    pitch_steps: float = -16.0,
    sub_oct_mix: float = 0.55,
    rumble_mix: float = 0.25,
    rumble_base_hz: float = 55.0,
    drive: float = 0.55,
    xover_hz: float = 280.0,
    quiet: bool = True,
) -> None:
    """
    Convert WAV file with advanced rumble effect using audio_effects module.

    This function follows a multi-step process:
    1. Convert to 16kHz mono as intermediate format
    2. Apply rumble_layered_with_fx effect (pitch shift, bass layers, noise, reverb, EQ, compression)
    3. Convert to final tinyplay format

    Args:
        input_path: Input WAV file path
        output_path: Output WAV file path
        sample_rate: Target sample rate (Hz)
        channels: Target channel count (1: mono, 2: stereo)
        sample_format: Target sample format (s16, s32, etc.)
        pitch_steps: Pitch shift in semitones (default: -16 = down ~1.3 octaves)
        sub_oct_mix: Sub-octave layer mix amount (0..1)
        rumble_mix: Synthetic rumble noise mix amount (0..1)
        rumble_base_hz: Base frequency for rumble generation
        drive: Distortion drive amount (0..1)
        xover_hz: Crossover frequency for high/low split
        quiet: Suppress FFmpeg output (default: True)

    Raises:
        RuntimeError: Audio processing or conversion failed
    """
    import subprocess
    from pathlib import Path

    from api.audio_effects import rumble_layered_with_fx

    # Create temporary file paths
    tmp_path = Path(output_path)
    tmp16 = tmp_path.with_suffix(".tmp16k_mono.wav")
    tmpfx16 = tmp_path.with_suffix(".tmp16k_mono_fx.wav")

    try:
        # Step 1: Convert to 16kHz mono intermediate format
        cmd = ["ffmpeg", "-y"]
        if quiet:
            cmd += ["-hide_banner", "-loglevel", "error"]
        cmd += [
            "-i",
            str(input_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-sample_fmt",
            "s16",
            str(tmp16),
        ]

        logger.debug(f"FFmpeg command (step 1): {' '.join(cmd)}")
        subprocess.run(cmd, check=True, capture_output=True, text=True)

        # Step 2: Apply rumble + fx (16k mono -> 16k mono with effects)
        logger.info("Applying rumble_layered_with_fx...")
        rumble_layered_with_fx(
            str(tmp16),
            str(tmpfx16),
            pitch_steps=pitch_steps,
            sub_oct_mix=sub_oct_mix,
            rumble_mix=rumble_mix,
            rumble_base_hz=rumble_base_hz,
            drive=drive,
            xover_hz=xover_hz,
        )

        # Step 3: Convert to final tinyplay format
        cmd = ["ffmpeg", "-y"]
        if quiet:
            cmd += ["-hide_banner", "-loglevel", "error"]
        cmd += [
            "-i",
            str(tmpfx16),
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
            "-sample_fmt",
            sample_format,
            str(output_path),
        ]

        logger.debug(f"FFmpeg command (step 3): {' '.join(cmd)}")
        subprocess.run(cmd, check=True, capture_output=True, text=True)

        logger.info(f"FFmpeg conversion with rumble completed: {output_path}")

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg conversion with rumble failed: {e.stderr}")
        raise RuntimeError(f"FFmpeg conversion with rumble failed: {e.stderr}")
    except Exception as e:
        logger.error(f"Rumble effect processing failed: {e}")
        raise RuntimeError(f"Rumble effect processing failed: {e}")

    finally:
        # Cleanup temporary files
        for tmp_file in [tmp16, tmpfx16]:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                    logger.debug(f"Removed temporary file: {tmp_file}")
                except Exception as e:
                    logger.warning(f"Failed to remove temporary file {tmp_file}: {e}")


def tinyplay_play(wav_path: str, card: int = 0, device: int = 1) -> None:
    """
    Play WAV file using tinyplay command.

    Args:
        wav_path: WAV file path to play
        card: ALSA card number
        device: ALSA device number

    Raises:
        RuntimeError: tinyplay playback failed
    """
    import subprocess

    cmd = ["tinyplay", f"-D{card}", f"-d{device}", str(wav_path)]

    logger.debug(f"tinyplay command: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"tinyplay playback completed: {wav_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"tinyplay playback failed: {e.stderr}")
        raise RuntimeError(f"tinyplay playback failed: {e.stderr}")


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
            tts_generate_wav(text, self.model, raw_wav_path)

            # Step 2: Convert WAV file (optional)
            if enable_ffmpeg:
                logger.info("Converting WAV file with FFmpeg...")
                if enable_rumble:
                    # Get advanced rumble parameters from config
                    pitch_steps = audio_config.get("rumble_pitch_steps", -16.0)
                    sub_oct_mix = audio_config.get("rumble_sub_oct_mix", 0.55)
                    rumble_mix = audio_config.get("rumble_mix", 0.25)
                    rumble_base_hz = audio_config.get("rumble_base_hz", 55.0)
                    drive = audio_config.get("rumble_drive", 0.55)
                    xover_hz = audio_config.get("rumble_xover_hz", 280.0)

                    ffmpeg_convert_for_tinyplay_with_rumble(
                        raw_wav_path,
                        final_wav_path,
                        sample_rate,
                        channels,
                        sample_format,
                        pitch_steps,
                        sub_oct_mix,
                        rumble_mix,
                        rumble_base_hz,
                        drive,
                        xover_hz,
                    )
                else:
                    ffmpeg_convert_for_tinyplay(
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
            tinyplay_play(playback_path, tinyplay_card, tinyplay_device)

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
