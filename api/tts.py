import os
import random
import time
from pathlib import Path

from loguru import logger
from openai import OpenAI

from api.utils import TTS_SETTINGS
from api.text_transform import transform_text

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

    # Verify the generated file
    import os

    if os.path.exists(output_path):
        file_size = os.path.getsize(output_path)
        logger.debug(f"Generated file size: {file_size} bytes")

        # Read first few bytes to check file format
        with open(output_path, "rb") as f:
            header = f.read(16)
            logger.debug(f"File header (first 16 bytes): {header.hex()}")

            # Check if it's a valid WAV file (should start with "RIFF")
            if not header.startswith(b"RIFF"):
                logger.warning("Generated file does not have RIFF header - may not be a valid WAV file")
    else:
        logger.error(f"Output file not created: {output_path}")

    logger.info(f"WAV file generated: {output_path}")


def ffmpeg_convert_for_tinyplay(
    input_path: str,
    output_path: str,
    sample_rate: int = 32000,
    channels: int = 2,
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
    sample_rate: int = 48000,
    channels: int = 2,
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


def convert_with_voice_fx(raw_wav_path: str, final_wav_path: str, audio_config: dict) -> None:
    """
    Voice processing dispatcher: selects pipeline based on effect_mode config.

    Modes:
      "ghost"  — Accumulating Ghosts (Heptapod B-inspired, pro mastering)
      "rumble" — Legacy rumble pipeline (granular pitch + sub-octave)
      "off"    — Format conversion only (no audio effects)
    """
    effect_mode = audio_config.get("effect_mode", "ghost")

    if effect_mode == "ghost":
        _convert_ghost(raw_wav_path, final_wav_path, audio_config)
    elif effect_mode == "rumble":
        _convert_rumble(raw_wav_path, final_wav_path, audio_config)
    else:
        # "off" — just format convert
        from api.audio_effects import sh
        sr = audio_config.get("sample_rate", 48000)
        ch = audio_config.get("channels", 2)
        fmt = audio_config.get("sample_format", "s16")
        sh([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(raw_wav_path),
            "-ar", str(sr), "-ac", str(ch), "-sample_fmt", fmt,
            str(final_wav_path),
        ])
        logger.info(f"[voice_fx] mode=off, format conversion only")

def _apply_speed_effect(in_wav: str, out_wav: str, audio_config: dict) -> None:
    """Apply playback speed effect (atempo or tape-style)."""
    speed_cfg = audio_config.get("speed", {})
    speed_mode = speed_cfg.get("mode", "off")

    if speed_mode == "off":
        return

    # Determine speed value: fixed or random range
    fixed_val = speed_cfg.get("value")
    if fixed_val is not None and fixed_val is not False:
        speed = float(fixed_val)
    else:
        rng = speed_cfg.get("range", {"min": 0.8, "max": 1.2})
        speed = random.uniform(rng["min"], rng["max"])

    sr = audio_config.get("sample_rate", 48000)
    ch = audio_config.get("channels", 2)
    fmt = audio_config.get("sample_format", "s16")

    if speed_mode == "atempo":
        # Pitch-preserving speed change
        # atempo only accepts 0.5-100.0, chain for extreme values
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", in_wav,
            "-af", f"atempo={speed}",
            "-ar", str(sr), "-ac", str(ch), "-sample_fmt", fmt,
            out_wav,
        ]
    elif speed_mode == "tape":
        # Tape-style: pitch shifts with speed (resample trick)
        new_rate = int(sr * speed)
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", in_wav,
            "-af", f"asetrate={new_rate},aresample={sr}",
            "-ar", str(sr), "-ac", str(ch), "-sample_fmt", fmt,
            out_wav,
        ]
    else:
        logger.warning(f"[speed_fx] Unknown mode: {speed_mode}, skipping")
        import shutil
        shutil.copy2(in_wav, out_wav)
        return

    logger.info(f"[speed_fx] mode={speed_mode} speed={speed:.3f}")
    import subprocess
    subprocess.run(cmd, check=True)

def _convert_ghost(raw_wav_path: str, final_wav_path: str, audio_config: dict) -> None:
    """Accumulating Ghosts pipeline."""
    from api.audio_effects import process_voice

    ghost_cfg = audio_config.get("ghost", {})
    seg_cfg = audio_config.get("segmentation", {})
    bloom_cfg = audio_config.get("bloom", {})
    gap_cfg = audio_config.get("gap_fill", {})
    reverb_cfg = audio_config.get("reverb", {})
    master_cfg = audio_config.get("mastering", {})
    global_cfg = audio_config.get("global_bloom", {})

    seed = random.randint(0, 2**31)

    logger.info(
        f"[ghost_fx] mode=ghost "
        f"ghost_linger={ghost_cfg.get('linger_s', 2.5)}s "
        f"reverb_wet={reverb_cfg.get('wet', 0.22)} seed={seed}"
    )
    # Ghost processing to intermediate or final path
    speed_cfg = audio_config.get("speed", {})
    speed_mode = speed_cfg.get("mode", "off")

    if speed_mode != "off":
        ghost_wav_path = final_wav_path + ".ghost.wav"
    else:
        ghost_wav_path = final_wav_path

    process_voice(
        in_wav=raw_wav_path,
        out_wav=ghost_wav_path,
        ghost_linger_s=ghost_cfg.get("linger_s", 2.5),
        ghost_level=ghost_cfg.get("level", 0.42),
        ghost_cutoff_start=ghost_cfg.get("cutoff_start", 550),
        ghost_cutoff_decay=ghost_cfg.get("cutoff_decay", 12),
        ghost_resonance=ghost_cfg.get("resonance", 0.3),
        silence_threshold=seg_cfg.get("silence_threshold", 0.015),
        min_segment_ms=seg_cfg.get("min_segment_ms", 40),
        max_segment_ms=seg_cfg.get("max_segment_ms", 280),
        bloom_attack_ms=bloom_cfg.get("attack_ms", 25),
        bloom_release_ms=bloom_cfg.get("release_ms", 60),
        gap_fill_level=gap_cfg.get("level", 0.25),
        gap_fill_cutoff=gap_cfg.get("cutoff", 500),
        reverb_room_size=reverb_cfg.get("room_size", 0.82),
        reverb_damping=reverb_cfg.get("damping", 0.45),
        reverb_wet=reverb_cfg.get("wet", 0.22),
        reverb_predelay_ms=reverb_cfg.get("predelay_ms", 15),
        saturation_drive=master_cfg.get("saturation_drive", 0.20),
        low_boost_db=master_cfg.get("low_boost_db", 2.5),
        mid_cut_db=master_cfg.get("mid_cut_db", -1.5),
        air_boost_db=master_cfg.get("air_boost_db", 1.0),
        comp_threshold_db=master_cfg.get("comp_threshold_db", -16),
        comp_ratio=master_cfg.get("comp_ratio", 2.5),
        stereo_width=audio_config.get("stereo_width", 0.25),
        global_attack_s=global_cfg.get("attack_s", 0.5),
        global_release_s=global_cfg.get("release_s", 0.4),
        voice_level=audio_config.get("voice_level", 0.58),
        out_sample_rate=audio_config.get("sample_rate", 48000),
        out_channels=audio_config.get("channels", 2),
        out_sample_format=audio_config.get("sample_format", "s16"),
        seed=seed,
    )

    # Apply speed effect
    if speed_mode != "off":
        _apply_speed_effect(ghost_wav_path, final_wav_path, audio_config)
        if os.path.exists(ghost_wav_path):
            os.remove(ghost_wav_path)

def _convert_rumble(raw_wav_path: str, final_wav_path: str, audio_config: dict) -> None:
    """Legacy rumble pipeline (v2)."""
    from api.audio_effects import process_voice_rumble

    pitch_range = audio_config.get("rumble_pitch_steps_range", {"min": -16.0, "max": -3.0})
    center_pitch = random.uniform(pitch_range["min"], pitch_range["max"])

    granular_cfg = audio_config.get("granular_pitch", {})
    formant_cfg = audio_config.get("formant_shift_range", {"min": 0.0, "max": 0.0})
    scatter_cfg = audio_config.get("grain_scatter", {})
    scatter_range = scatter_cfg.get("amount_range", {"min": 0.0, "max": 0.0})
    speed_cfg = audio_config.get("speed_range", {"min": 1.0, "max": 1.0})
    seed = random.randint(0, 2**31)

    logger.info(f"[rumble_fx] mode=rumble pitch={center_pitch:+.1f}st seed={seed}")

    process_voice_rumble(
        in_wav=raw_wav_path,
        out_wav=final_wav_path,
        center_pitch=center_pitch,
        pitch_wander_range=granular_cfg.get("wander_range", 4.0),
        pitch_lfo_speed=granular_cfg.get("lfo_speed", 0.4),
        formant_shift=random.uniform(formant_cfg["min"], formant_cfg["max"]),
        sub_oct_mix=audio_config.get("rumble_sub_oct_mix", 0.55),
        rumble_mix=audio_config.get("rumble_mix", 0.25),
        rumble_base_hz=audio_config.get("rumble_base_hz", 55.0),
        drive=audio_config.get("rumble_drive", 0.55),
        xover_hz=audio_config.get("rumble_xover_hz", 280.0),
        scatter_amount=random.uniform(scatter_range["min"], scatter_range["max"]),
        speed=random.uniform(speed_cfg["min"], speed_cfg["max"]),
        out_sample_rate=audio_config.get("sample_rate", 48000),
        out_channels=audio_config.get("channels", 2),
        out_sample_format=audio_config.get("sample_format", "s16"),
        seed=seed,
    )


def tinyplay_play(wav_path: str, card: int = 0, device: int = 1, playback_device: str = "") -> None:
    """
    Play WAV file using aplay (ALSA) or tinyplay (legacy fallback).

    When playback_device is set (e.g. "dmixer"), uses aplay -D <device>.
    This routes through the dmix plugin, which keeps the ALSA device open
    and prevents amp pop noise caused by the driver toggling pa_gpio.

    Args:
        wav_path: WAV file path to play
        card: ALSA card number (legacy tinyplay fallback)
        device: ALSA device number (legacy tinyplay fallback)
        playback_device: ALSA device name for aplay (e.g. "dmixer", "default")

    Raises:
        RuntimeError: playback failed
    """
    import subprocess

    if playback_device:
        cmd = ["aplay", "-D", playback_device, str(wav_path)]
    else:
        # Legacy fallback: tinyplay (排他アクセス、ポップノイズあり)
        cmd = ["tinyplay", f"-D{card}", f"-d{device}", str(wav_path)]

    logger.debug(f"playback command: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"playback completed: {wav_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"playback failed: {e.stderr}")
        raise RuntimeError(f"playback failed: {e.stderr}")


# ==========================================================================


class StackFlowTTSClient:
    def __init__(self, config: dict):
        self.config = config
        self.set_params(config)
        logger.info("StackFlowTTSClient initialized (HTTP API mode)")

    def set_params(self, config: dict):
        lang = config.get("common").get("lang")
        # TTS always uses Japanese model regardless of LLM language
        self.model = TTS_SETTINGS.get("ja").get("model")

        logger.info("[TTS info]")
        logger.info(f"lang: {lang} (TTS forced to ja)")
        logger.info(f"model: {self.model}")

    def _transform_text(self, text: str) -> str:
        """Apply text transformations based on config."""
        tt_cfg = self.config.get("audio", {}).get("text_transform", {})
        if not tt_cfg.get("enabled", False):
            return text

        # Hiragana/elongation transforms only apply to Japanese
        lang = self.config.get("common", {}).get("lang", "ja")
        if lang != "ja":
            return text

        return transform_text(
            text,
            to_hira=tt_cfg.get("to_hiragana", True),
            elongation_mode=tt_cfg.get("elongation_mode", "off"),
            elongation_probability=tt_cfg.get("elongation_probability", 0.5),
            elongation_length_min=tt_cfg.get("elongation_length", {}).get("min", 2),
            elongation_length_max=tt_cfg.get("elongation_length", {}).get("max", 5),
            seed=random.randint(0, 2**31),
        )

    def prepare_wav_sync(self, text: str) -> str | None:
        """
        Synchronous version of prepare_wav for use with asyncio.to_thread.

        Generate and convert WAV file, return path for playback.
        """
        text = self._transform_text(text)

        audio_config = self.config.get("audio", {})

        temp_wav_dir = audio_config.get("temp_wav_dir", "/tmp")
        enable_ffmpeg = audio_config.get("enable_ffmpeg_convert", True)
        enable_rumble = audio_config.get("enable_rumble_effect", False)
        sample_rate = audio_config.get("sample_rate", 48000)
        channels = audio_config.get("channels", 2)
        sample_format = audio_config.get("sample_format", "s16")

        os.makedirs(temp_wav_dir, exist_ok=True)

        # --- Debug raw audio mode ---
        debug_raw = audio_config.get("debug_raw_audio", False)
        if debug_raw:
            debug_dir = "/tmp/bi_debug"
            os.makedirs(debug_dir, exist_ok=True)
            timestamp = time.time()
            raw_wav_path = os.path.join(debug_dir, f"tts_raw_{timestamp}.wav")
            try:
                logger.info(f"[RAW-AUDIO] Generating WAV (no FFmpeg): {text[:50]}...")
                tts_generate_wav(text, self.model, raw_wav_path)
                logger.info(f"[RAW-AUDIO] Saved: {raw_wav_path}")
                return raw_wav_path
            except Exception as e:
                logger.error(f"[RAW-AUDIO] WAV generation failed: {e}")
                return None

        timestamp = time.time()
        raw_wav_path = os.path.join(temp_wav_dir, f"tts_raw_{timestamp}.wav")
        final_wav_path = os.path.join(temp_wav_dir, f"tts_final_{timestamp}.wav")

        try:
            logger.info(f"Generating WAV file: {text[:50]}...")
            tts_generate_wav(text, self.model, raw_wav_path)

        except Exception as e:
            logger.error(f"WAV generation failed: {e}")
            for p in [raw_wav_path, final_wav_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            return None

        try:
            if enable_ffmpeg:
                logger.info("Converting WAV file with FFmpeg...")
                if enable_rumble:
                    convert_with_voice_fx(raw_wav_path, final_wav_path, audio_config)
                else:
                    ffmpeg_convert_for_tinyplay(
                        raw_wav_path, final_wav_path,
                        32000, channels, sample_format,
                    )
                # Remove raw file, keep final
                if os.path.exists(raw_wav_path):
                    os.remove(raw_wav_path)
                return final_wav_path
            else:
                return raw_wav_path

        except Exception as e:
            logger.error(f"WAV converting failed: {e}")
            for p in [raw_wav_path, final_wav_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            return None

    async def prepare_wav(self, text: str) -> str | None:
        """
        Generate and convert WAV file, return path for playback.

        Args:
            text: Text to synthesize

        Returns:
            str: Path to the playback-ready WAV file, or None on failure
        """
        text = self._transform_text(text)

        audio_config = self.config.get("audio", {})

        temp_wav_dir = audio_config.get("temp_wav_dir", "/tmp")
        enable_ffmpeg = audio_config.get("enable_ffmpeg_convert", True)
        enable_rumble = audio_config.get("enable_rumble_effect", False)
        sample_rate = audio_config.get("sample_rate", 48000)
        channels = audio_config.get("channels", 2)
        sample_format = audio_config.get("sample_format", "s16")

        os.makedirs(temp_wav_dir, exist_ok=True)

        timestamp = time.time()
        raw_wav_path = os.path.join(temp_wav_dir, f"tts_raw_{timestamp}.wav")
        final_wav_path = os.path.join(temp_wav_dir, f"tts_final_{timestamp}.wav")

        try:
            logger.info(f"Generating WAV file: {text[:50]}...")
            tts_generate_wav(text, self.model, raw_wav_path)

            if enable_ffmpeg:
                logger.info("Converting WAV file with FFmpeg...")
                if enable_rumble:
                    convert_with_voice_fx(raw_wav_path, final_wav_path, audio_config)
                else:
                    ffmpeg_convert_for_tinyplay(
                        raw_wav_path, final_wav_path,
                        32000, channels, sample_format,
                    )
                # Remove raw file, keep final
                if os.path.exists(raw_wav_path):
                    os.remove(raw_wav_path)
                return final_wav_path
            else:
                return raw_wav_path

        except Exception as e:
            logger.error(f"WAV preparation failed: {e}")
            for p in [raw_wav_path, final_wav_path]:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            return None

    def start_playback(self, wav_path: str) -> "subprocess.Popen":
            """
            Start WAV playback using aplay/tinyplay (non-blocking Popen).
            """
            import subprocess

            audio_config = self.config.get("audio", {})
            playback_device = audio_config.get("playback_device", "")

            if playback_device:
                cmd = ["aplay", "-D", playback_device, str(wav_path)]
            else:
                card = audio_config.get("tinyplay_card", 0)
                device = audio_config.get("tinyplay_device", 1)
                cmd = ["tinyplay", f"-D{card}", f"-d{device}", str(wav_path)]

            logger.info(f"Starting playback: {' '.join(cmd)}")
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            return proc

    def play_wav_sync(self, wav_path: str) -> None:
            """
            Play WAV file using aplay/tinyplay (blocking, for use with asyncio.to_thread).
            """
            import subprocess

            audio_config = self.config.get("audio", {})
            debug_raw = audio_config.get("debug_raw_audio", False)
            if debug_raw:
                cmd = ["aplay", str(wav_path)]
                logger.info(f"[RAW-AUDIO] Playback: {' '.join(cmd)}")
                try:
                    subprocess.run(cmd, check=True, capture_output=True, text=True)
                    logger.info(f"[RAW-AUDIO] Playback completed: {wav_path}")
                except subprocess.CalledProcessError as e:
                    logger.error(f"[RAW-AUDIO] Playback failed: {e.stderr}")
                    raise RuntimeError(f"[RAW-AUDIO] Playback failed: {e.stderr}")
                return

            playback_device = audio_config.get("playback_device", "")

            if playback_device:
                cmd = ["aplay", "-D", playback_device, str(wav_path)]
            else:
                card = audio_config.get("tinyplay_card", 0)
                device = audio_config.get("tinyplay_device", 1)
                cmd = ["tinyplay", f"-D{card}", f"-d{device}", str(wav_path)]

            logger.info(f"Starting playback: {' '.join(cmd)}")

            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                logger.info(f"playback completed: {wav_path}")
            except subprocess.CalledProcessError as e:
                logger.error(f"playback failed: {e.stderr}")
                raise RuntimeError(f"playback failed: {e.stderr}")

    def cleanup_wav(self, wav_path: str) -> None:
        """Remove temporary WAV file."""
        if self.config.get("audio", {}).get("debug_raw_audio", False):
            logger.debug(f"[RAW-AUDIO] Keeping file: {wav_path}")
            return
        if wav_path and os.path.exists(wav_path):
            try:
                os.remove(wav_path)
                logger.debug(f"Removed temporary file: {wav_path}")
            except Exception as e:
                logger.warning(f"Failed to remove {wav_path}: {e}")

    async def speak_to_file(self, text: str, on_start_callback=None, on_end_callback=None) -> None:
        """
        Generate WAV file from text and play it using tinyplay.

        This method uses OpenAI-compatible TTS API to generate WAV file,
        optionally converts it with FFmpeg, and plays it using tinyplay command.

        Args:
            text: Text to synthesize
            on_start_callback: Optional callback to call before tinyplay starts (args: text)
            on_end_callback: Optional callback to call after tinyplay ends (args: text, error)

        Raises:
            Exception: WAV generation, conversion, or playback failed
        """
        text = self._transform_text(text)

        audio_config = self.config.get("audio", {})

        # Get configuration
        temp_wav_dir = audio_config.get("temp_wav_dir", "/tmp")
        enable_ffmpeg = audio_config.get("enable_ffmpeg_convert", True)
        enable_rumble = audio_config.get("enable_rumble_effect", False)
        sample_rate = audio_config.get("sample_rate", 48000)
        channels = audio_config.get("channels", 2)
        sample_format = audio_config.get("sample_format", "s16")
        tinyplay_card = audio_config.get("tinyplay_card", 0)
        tinyplay_device = audio_config.get("tinyplay_device", 1)
        playback_device = audio_config.get("playback_device", "")

        # Ensure temp directory exists
        os.makedirs(temp_wav_dir, exist_ok=True)
        logger.debug(f"Using temp directory: {temp_wav_dir}")

        # Generate temporary file paths
        timestamp = time.time()
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
                    convert_with_voice_fx(raw_wav_path, final_wav_path, audio_config)
                else:
                    ffmpeg_convert_for_tinyplay(
                        raw_wav_path,
                        final_wav_path,
                        32000,
                        channels,
                        sample_format,
                    )
                playback_path = final_wav_path
            else:
                playback_path = raw_wav_path

            # Step 3: Play WAV file using tinyplay
            logger.info("Playing WAV file with tinyplay...")

            # Call on_start_callback before tinyplay starts
            if on_start_callback:
                try:
                    on_start_callback(text)
                except Exception as e:
                    logger.error(f"on_start_callback failed: {e}")

            # Execute tinyplay
            tinyplay_play(playback_path, tinyplay_card, tinyplay_device, playback_device)

            # Call on_end_callback after tinyplay ends successfully
            if on_end_callback:
                try:
                    on_end_callback(text, error=False)
                except Exception as e:
                    logger.error(f"on_end_callback failed: {e}")

            logger.info("TTS playback completed successfully")

        except Exception as e:
            logger.error(f"TTS speak_to_file failed: {e}")

            # Call on_end_callback with error flag
            if on_end_callback:
                try:
                    on_end_callback(text, error=True)
                except Exception as callback_error:
                    logger.error(f"on_end_callback (error case) failed: {callback_error}")

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
