"""
Audio effects module for TTS processing with rumble effects.

This module provides advanced audio processing capabilities including:
- Pitch shifting
- Low-frequency rumble generation
- Multi-band filtering and crossover
- Dynamic envelope following
- FFmpeg-based effects chain

Based on: https://github.com/obake2ai/BI_M5_QwenSoftPrefix
"""

import math
import shlex
import subprocess
from pathlib import Path
from typing import Optional, Sequence, Union

import numpy as np
import soundfile as sf
from loguru import logger
from scipy import signal

# Working directory for temporary files
WORKDIR = Path("./tmp/audio_work")
WORKDIR.mkdir(exist_ok=True, parents=True)


# ========== Command Execution Helpers ==========


def sh(cmd: Union[str, Sequence[str]], check: bool = True) -> subprocess.CompletedProcess:
    """
    Command execution helper with better error reporting.

    Args:
        cmd: Command string or list of arguments
        check: Raise exception on non-zero exit code

    Returns:
        CompletedProcess instance

    Raises:
        subprocess.CalledProcessError: Command failed
    """
    if isinstance(cmd, (list, tuple)):
        printable = " ".join(shlex.quote(str(x)) for x in cmd)
        shell = False
    else:
        printable = cmd
        shell = True

    logger.debug(f"$ {printable}")
    p = subprocess.run(
        cmd,
        shell=shell,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if check and p.returncode != 0:
        logger.error(p.stdout)
        raise subprocess.CalledProcessError(p.returncode, printable, output=p.stdout)
    return p


# ========== Audio Conversion & I/O ==========


def to_wav_16k_mono(in_path: str, out_path: str) -> None:
    """Convert audio to 16kHz mono WAV format."""
    sh(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(in_path),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-vn",
            str(out_path),
        ]
    )


def ffmpeg_apply_filter(in_wav: str, out_wav: str, afilter: str) -> None:
    """Apply FFmpeg audio filter to WAV file."""
    sh(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(in_wav),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            afilter,
            str(out_wav),
        ]
    )


def list_ffmpeg_filters() -> str:
    """List all available FFmpeg filters."""
    return sh(["ffmpeg", "-hide_banner", "-filters"]).stdout


# Cache FFmpeg filters list
FFMPEG_FILTERS_TEXT = list_ffmpeg_filters()


def ffmpeg_has_filter(filter_name: str) -> bool:
    """Check if FFmpeg has a specific filter available."""
    return (f" {filter_name} " in FFMPEG_FILTERS_TEXT) or (f"\t{filter_name} " in FFMPEG_FILTERS_TEXT)


def load16k(path: str) -> np.ndarray:
    """
    Load audio file as 16kHz mono array with DC offset removal.

    Args:
        path: Audio file path

    Returns:
        Audio data as float32 numpy array
    """
    y, sr = sf.read(path)
    if y.ndim > 1:
        y = y.mean(axis=1)
    if sr != 16000:
        tmp = str(WORKDIR / "_tmp_16k.wav")
        to_wav_16k_mono(path, tmp)
        y, sr = sf.read(tmp)
        if y.ndim > 1:
            y = y.mean(axis=1)
    y = y.astype(np.float32)
    # Remove DC offset
    y = y - float(np.mean(y))
    return y


def write16k(path: str, y: np.ndarray) -> None:
    """Write audio array to 16kHz WAV file."""
    y = np.nan_to_num(y.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    sf.write(str(path), y, 16000)


# ========== Audio Processing Utilities ==========


def peak_norm(y: np.ndarray, peak: float = 0.95) -> np.ndarray:
    """Normalize audio to peak amplitude."""
    y = np.nan_to_num(y.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
    m = float(np.max(np.abs(y)) + 1e-9)
    if m < 1e-8:
        return y
    return (peak / m) * y


def rms(y: np.ndarray) -> float:
    """Calculate RMS (root mean square) of audio signal."""
    return float(np.sqrt(np.mean(y * y) + 1e-12))


def atempo_chain(rate: float) -> str:
    """
    Generate FFmpeg atempo filter chain for arbitrary rates.

    FFmpeg atempo filter has 0.5-2.0 range limit, so we chain
    multiple atempo filters to achieve any rate.
    """
    if rate <= 0:
        raise ValueError("rate must be > 0")
    parts = []
    r = float(rate)
    while r > 2.0 + 1e-9:
        parts.append(2.0)
        r /= 2.0
    while r < 0.5 - 1e-9:
        parts.append(0.5)
        r /= 0.5
    if abs(r - 1.0) > 1e-6:
        parts.append(r)
    if not parts:
        parts = [1.0]
    return ",".join([f"atempo={p:.6f}" for p in parts])


# ========== Pitch Shifting ==========


def pitch_shift_ffmpeg_16k(
    in_wav_16k: str,
    out_wav_16k: str,
    semitone_steps: float,
    method: str = "auto",
) -> None:
    """
    Pitch shift 16kHz mono WAV while maintaining tempo.

    Args:
        in_wav_16k: Input 16kHz mono WAV path
        out_wav_16k: Output 16kHz mono WAV path
        semitone_steps: Pitch shift in semitones (e.g., -12 = down 1 octave)
        method: "auto", "rubberband", or "asetrate"

    Raises:
        RuntimeError: All methods failed
    """
    sr = 16000
    ratio = 2 ** (semitone_steps / 12.0)  # pitch scale

    if method == "auto":
        methods = []
        if ffmpeg_has_filter("rubberband"):
            methods.append("rubberband")
        methods.append("asetrate")  # Always try this as fallback
    else:
        methods = [method]

    last_err = None
    for m in methods:
        if m == "rubberband":
            af = f"rubberband=pitch={ratio:.6f}:tempo=1"
        elif m == "asetrate":
            factor = ratio
            atempo = atempo_chain(1.0 / factor)
            af = ",".join(
                [
                    f"asetrate={sr*factor:.3f}",
                    atempo,
                    f"aresample={sr}",
                ]
            )
        else:
            raise ValueError(f"Unknown method: {m}")

        try:
            sh(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    str(in_wav_16k),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-af",
                    af,
                    str(out_wav_16k),
                ]
            )
            return
        except subprocess.CalledProcessError as e:
            last_err = e
            logger.warning(f"[pitch_shift] method '{m}' failed -> trying fallback ...")
            continue

    # All methods failed
    if last_err is not None:
        raise last_err
    raise RuntimeError("pitch_shift_ffmpeg_16k failed unexpectedly")


# ========== Signal Processing ==========


def envelope_follower(
    x: np.ndarray,
    sr: int = 16000,
    attack_ms: float = 5.0,
    release_ms: float = 120.0,
    power: float = 1.25,
) -> np.ndarray:
    """
    Extract envelope from audio signal (0..1 range) without NaN artifacts.

    Args:
        x: Input audio signal
        sr: Sample rate
        attack_ms: Attack time in milliseconds
        release_ms: Release time in milliseconds
        power: Power curve for envelope shaping

    Returns:
        Envelope signal (0..1 range)
    """
    x = np.abs(np.nan_to_num(x.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0))
    # 1-pole smoothing (attack/release)
    a_a = math.exp(-1.0 / (max(1.0, attack_ms) * 0.001 * sr))
    a_r = math.exp(-1.0 / (max(1.0, release_ms) * 0.001 * sr))
    env = np.zeros_like(x, dtype=np.float32)
    prev = 0.0
    for i, v in enumerate(x):
        a = a_a if v > prev else a_r
        prev = a * prev + (1.0 - a) * float(v)
        env[i] = prev

    # Normalize (0..1) -> clip -> power curve
    env = env / (float(np.max(env)) + 1e-9)
    env = np.clip(env, 0.0, 1.0)
    env = np.power(env, float(power)).astype(np.float32)
    return env


def butter_filter(y: np.ndarray, sr: int, btype: str, cutoff, order: int = 4) -> np.ndarray:
    """
    Apply Butterworth filter to audio signal.

    Args:
        y: Input signal
        sr: Sample rate
        btype: Filter type ("lowpass", "highpass", "bandpass")
        cutoff: Cutoff frequency (Hz) or [low, high] for bandpass
        order: Filter order

    Returns:
        Filtered signal
    """
    b, a = signal.butter(order, cutoff, btype=btype, fs=sr)
    return signal.lfilter(b, a, y).astype(np.float32)


def tanh_drive(y: np.ndarray, drive: float) -> np.ndarray:
    """Apply soft clipping distortion using tanh."""
    if drive <= 0:
        return y.astype(np.float32)
    k = 1.0 + float(drive) * 5.0
    return np.tanh(k * y).astype(np.float32)


# ========== Rumble Generation ==========


def make_rumble_noise(
    voice: np.ndarray,
    sr: int,
    base_hz: float = 55.0,
    amount: float = 0.25,
    seed: int = 0,
) -> np.ndarray:
    """
    Generate low-frequency rumble noise modulated by voice envelope.

    Args:
        voice: Input voice signal
        sr: Sample rate
        base_hz: Base frequency for rumble (Hz)
        amount: Rumble amount (0..1)
        seed: Random seed

    Returns:
        Rumble noise signal
    """
    if amount <= 0:
        return np.zeros_like(voice, dtype=np.float32)

    rng = np.random.default_rng(seed)
    n = len(voice)
    t = np.arange(n) / sr

    env = envelope_follower(voice, sr=sr, attack_ms=8, release_ms=220, power=1.35)

    # Brown-like noise (natural low-frequency content)
    white = rng.standard_normal(n).astype(np.float32)
    brown = np.cumsum(white).astype(np.float32)
    brown = brown / (np.max(np.abs(brown)) + 1e-9)

    # Synthesize multiple bands to avoid "hum" artifacts
    def band(low, high):
        return butter_filter(brown, sr, "bandpass", [low, high], order=4)

    b1 = band(max(20.0, base_hz * 0.45), min(650.0, base_hz * 2.2))
    b2 = band(max(20.0, base_hz * 0.90), min(650.0, base_hz * 3.6))
    low_wide = butter_filter(brown, sr, "lowpass", min(220.0, base_hz * 3.0), order=4)

    rum = (0.55 * low_wide + 0.30 * b1 + 0.15 * b2).astype(np.float32)

    # Add slow LFO modulation
    lfo_f = 0.25 + 0.35 * rng.random()
    lfo = (0.65 + 0.35 * np.sin(2 * np.pi * lfo_f * t + 2 * np.pi * rng.random())).astype(np.float32)

    rum = rum * env * lfo

    # Adjust level: relative to voice RMS
    target = rms(voice) * (0.9 * amount)
    rum = rum * (target / (rms(rum) + 1e-9))
    return rum.astype(np.float32)


# ========== Main Rumble Effect Functions ==========


def rumble_layered(
    in_wav_16k: str,
    out_wav_16k: str,
    pitch_steps: float = -6.0,
    sub_oct_mix: float = 0.55,
    rumble_mix: float = 0.25,
    rumble_base_hz: float = 55.0,
    drive: float = 0.55,
    xover_hz: float = 280.0,
    seed: int = 42,
) -> None:
    """
    Apply layered rumble effect with pitch shifting and crossover filtering.

    This is the core rumble processing function that:
    1. Pitch shifts the input down (main and sub layers)
    2. Applies low-pass filtering to create bass layers
    3. Generates synthetic rumble noise
    4. Combines layers with crossover filtering
    5. Applies drive and normalization

    Args:
        in_wav_16k: Input 16kHz mono WAV path
        out_wav_16k: Output 16kHz mono WAV path
        pitch_steps: Main pitch shift in semitones (e.g., -6 = down 6 semitones)
        sub_oct_mix: Sub-octave layer mix amount (0..1)
        rumble_mix: Synthetic rumble noise mix amount (0..1)
        rumble_base_hz: Base frequency for rumble generation
        drive: Distortion drive amount (0..1)
        xover_hz: Crossover frequency for high/low split
        seed: Random seed for rumble generation
    """
    sr = 16000
    dry = load16k(in_wav_16k)

    # Pitch shift (main/sub) with FFmpeg, then mix in Python
    main_ps = str(WORKDIR / "_r2_main.wav")
    sub_ps = str(WORKDIR / "_r2_sub.wav")
    pitch_shift_ffmpeg_16k(in_wav_16k, main_ps, pitch_steps, method="auto")
    pitch_shift_ffmpeg_16k(in_wav_16k, sub_ps, pitch_steps - 12.0, method="auto")

    main = load16k(main_ps)
    sub = load16k(sub_ps)

    n = min(len(dry), len(main), len(sub))
    if n < sr * 0.2:
        raise RuntimeError(f"audio too short after pitch shift: n={n}")
    dry, main, sub = dry[:n], main[:n], sub[:n]

    # Low-frequency bass layers
    low_main = butter_filter(main, sr, "lowpass", 420, order=4)
    sub_lp_hz = float(min(700.0, max(220.0, rumble_base_hz * 6.0)))
    low_sub = butter_filter(sub, sr, "lowpass", sub_lp_hz, order=4)

    # Gate sub layer to avoid continuous drone
    gate = envelope_follower(main, sr=sr, attack_ms=6, release_ms=180, power=1.05)
    low_sub = low_sub * gate

    noise = make_rumble_noise(main, sr, base_hz=rumble_base_hz, amount=rumble_mix, seed=seed)

    low_bus = low_main + float(sub_oct_mix) * low_sub + noise
    low_bus = tanh_drive(low_bus, drive)

    # Crossover: high frequencies from main, low frequencies from low_bus
    high_voice = butter_filter(main, sr, "highpass", xover_hz, order=4)
    low_rumble = butter_filter(low_bus, sr, "lowpass", xover_hz, order=4)

    mix = high_voice + low_rumble
    mix = mix - float(np.mean(mix))
    mix = peak_norm(mix, 0.95)

    write16k(out_wav_16k, mix)


def rumble_layered_with_fx(in_wav_16k: str, out_wav_16k: str, **kwargs) -> None:
    """
    Apply layered rumble effect with additional reverb, EQ, compression, and limiting.

    This is the top-level rumble effect function that:
    1. Calls rumble_layered() for core processing
    2. Applies post-processing effects chain:
       - Echo/reverb
       - EQ boost at 140Hz
       - Dynamic compression
       - Limiter

    Args:
        in_wav_16k: Input 16kHz mono WAV path
        out_wav_16k: Output 16kHz mono WAV path
        **kwargs: Additional arguments passed to rumble_layered()
    """
    tmp = str(WORKDIR / "_tmp_r3_base.wav")
    rumble_layered(in_wav_16k, tmp, **kwargs)

    # Post-processing: reverb + EQ + compression + limiter
    af = ",".join(
        [
            "aecho=0.8:0.85:120|240:0.25|0.18",
            "equalizer=f=140:t=q:w=1.1:g=3",
            "acompressor=threshold=0.18:ratio=4:attack=15:release=260:makeup=1.5",
            "alimiter=limit=0.97",
        ]
    )
    ffmpeg_apply_filter(tmp, out_wav_16k, af)


# ========== Logging ==========

logger.info(f"FFmpeg has rubberband: {ffmpeg_has_filter('rubberband')}")
logger.info(f"FFmpeg has asubboost: {ffmpeg_has_filter('asubboost')}")
