"""
Audio effects module for TTS processing with rumble effects.

This module provides advanced audio processing capabilities including:
- Granular time-varying pitch shifting
- Formant shifting
- Low-frequency rumble generation
- Multi-band filtering and crossover
- Dynamic envelope following
- Grain scatter
- FFmpeg-based effects chain (consolidated for performance)

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
    if isinstance(cmd, (list, tuple)):
        printable = " ".join(shlex.quote(str(x)) for x in cmd)
        shell = False
    else:
        printable = cmd
        shell = True

    logger.debug(f"$ {printable}")
    p = subprocess.run(
        cmd, shell=shell, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    if check and p.returncode != 0:
        logger.error(p.stdout)
        raise subprocess.CalledProcessError(p.returncode, printable, output=p.stdout)
    return p


# ========== Audio Conversion & I/O ==========


def to_wav_16k_mono(in_path: str, out_path: str) -> None:
    """Convert audio to 16kHz mono WAV format."""
    sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(in_path), "-ac", "1", "-ar", "16000", "-vn", str(out_path)])


def ffmpeg_apply_filter(in_wav: str, out_wav: str, afilter: str) -> None:
    """Apply FFmpeg audio filter to WAV file."""
    sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(in_wav), "-ac", "1", "-ar", "16000", "-af", afilter, str(out_wav)])


def list_ffmpeg_filters() -> str:
    """List all available FFmpeg filters."""
    return sh(["ffmpeg", "-hide_banner", "-filters"]).stdout


# Cache FFmpeg filters list
FFMPEG_FILTERS_TEXT = list_ffmpeg_filters()


def ffmpeg_has_filter(filter_name: str) -> bool:
    """Check if FFmpeg has a specific filter available."""
    return (f" {filter_name} " in FFMPEG_FILTERS_TEXT) or (
        f"\t{filter_name} " in FFMPEG_FILTERS_TEXT
    )


def load16k(path: str) -> np.ndarray:
    """Load audio file as 16kHz mono float32 array with DC offset removal."""
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
    """Generate FFmpeg atempo filter chain for arbitrary rates."""
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


# ========== Signal Processing ==========


def envelope_follower(
    x: np.ndarray, sr: int = 16000,
    attack_ms: float = 5.0, release_ms: float = 120.0, power: float = 1.25,
) -> np.ndarray:
    """Extract envelope from audio signal (0..1 range)."""
    x = np.abs(np.nan_to_num(x.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0))
    a_a = math.exp(-1.0 / (max(1.0, attack_ms) * 0.001 * sr))
    a_r = math.exp(-1.0 / (max(1.0, release_ms) * 0.001 * sr))
    env = np.zeros_like(x, dtype=np.float32)
    prev = 0.0
    for i, v in enumerate(x):
        a = a_a if v > prev else a_r
        prev = a * prev + (1.0 - a) * float(v)
        env[i] = prev
    env = env / (float(np.max(env)) + 1e-9)
    env = np.clip(env, 0.0, 1.0)
    return np.power(env, float(power)).astype(np.float32)


def butter_filter(
    y: np.ndarray, sr: int, btype: str, cutoff, order: int = 4,
) -> np.ndarray:
    """Apply Butterworth filter to audio signal."""
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
    voice: np.ndarray, sr: int,
    base_hz: float = 55.0, amount: float = 0.25, seed: int = 0,
) -> np.ndarray:
    """Generate low-frequency rumble noise modulated by voice envelope."""
    if amount <= 0:
        return np.zeros_like(voice, dtype=np.float32)

    rng = np.random.default_rng(seed)
    n = len(voice)
    t = np.arange(n) / sr

    env = envelope_follower(voice, sr=sr, attack_ms=8, release_ms=220, power=1.35)

    white = rng.standard_normal(n).astype(np.float32)
    brown = np.cumsum(white).astype(np.float32)
    brown = brown / (np.max(np.abs(brown)) + 1e-9)

    def band(low, high):
        return butter_filter(brown, sr, "bandpass", [low, high], order=4)

    b1 = band(max(20.0, base_hz * 0.45), min(650.0, base_hz * 2.2))
    b2 = band(max(20.0, base_hz * 0.90), min(650.0, base_hz * 3.6))
    low_wide = butter_filter(brown, sr, "lowpass", min(220.0, base_hz * 3.0), order=4)

    rum = (0.55 * low_wide + 0.30 * b1 + 0.15 * b2).astype(np.float32)

    lfo_f = 0.25 + 0.35 * rng.random()
    lfo = (0.65 + 0.35 * np.sin(
        2 * np.pi * lfo_f * t + 2 * np.pi * rng.random()
    )).astype(np.float32)

    rum = rum * env * lfo
    target = rms(voice) * (0.9 * amount)
    rum = rum * (target / (rms(rum) + 1e-9))
    return rum.astype(np.float32)


# ========== Granular Time-Varying Pitch ==========


def generate_wandering_lfo(
    n_samples: int, sr: int = 16000,
    center: float = 0.0, wander_range: float = 1.0,
    lfo_speed: float = 0.3, num_harmonics: int = 4, seed: int = 42,
) -> np.ndarray:
    """
    Generate a smooth, organic modulation curve.

    Uses sum-of-sinusoids with random phases to create
    non-periodic, natural-sounding modulation.

    Args:
        n_samples: Length in samples
        sr: Sample rate
        center: Center value of the output curve
        wander_range: Max deviation from center (±)
        lfo_speed: Base modulation speed in Hz
        num_harmonics: Number of sinusoid layers
        seed: Random seed

    Returns:
        Modulation curve (float32)
    """
    rng = np.random.default_rng(seed)
    t = np.arange(n_samples) / sr

    curve = np.zeros(n_samples, dtype=np.float64)
    total_weight = 0.0

    for h in range(num_harmonics):
        freq = lfo_speed * (0.7 + 0.6 * h) * (0.85 + 0.3 * rng.random())
        phase = rng.random() * 2 * np.pi
        weight = 1.0 / (1.0 + 0.5 * h)
        curve += weight * np.sin(2 * np.pi * freq * t + phase)
        total_weight += weight

    curve = np.clip(curve / (total_weight + 1e-9), -1.0, 1.0)
    return (center + wander_range * curve).astype(np.float32)


def granular_pitch_shift(
    y: np.ndarray, sr: int, pitch_curve_semitones: np.ndarray,
    grain_ms: float = 60, hop_ms: float = 15,
) -> np.ndarray:
    """
    Time-varying pitch shift using granular resynthesis.

    Args:
        y: Input audio (float32)
        sr: Sample rate
        pitch_curve_semitones: Per-sample pitch shift in semitones
        grain_ms: Grain size in ms
        hop_ms: Hop size in ms

    Returns:
        Pitch-shifted audio (float32)
    """
    grain_samples = int(grain_ms * sr / 1000)
    hop_samples = int(hop_ms * sr / 1000)
    n = len(y)
    window = np.hanning(grain_samples).astype(np.float32)

    out_len = n + grain_samples * 2
    out = np.zeros(out_len, dtype=np.float64)
    out_norm = np.zeros(out_len, dtype=np.float64)

    read_pos = 0
    out_pos = 0

    while read_pos + grain_samples <= n and out_pos + grain_samples < out_len:
        center = min(read_pos + grain_samples // 2, n - 1)
        semitones = float(pitch_curve_semitones[center])
        ratio = 2.0 ** (semitones / 12.0)

        if abs(ratio - 1.0) > 0.001:
            read_len = int(grain_samples * ratio)
            read_len = max(2, min(read_len, n - read_pos))
            src = y[read_pos:read_pos + read_len].astype(np.float64)
            if len(src) < 2:
                read_pos += hop_samples
                out_pos += hop_samples
                continue
            x_old = np.linspace(0, 1, len(src))
            x_new = np.linspace(0, 1, grain_samples)
            grain = np.interp(x_new, x_old, src).astype(np.float32) * window
        else:
            grain = y[read_pos:read_pos + grain_samples].copy() * window

        end = out_pos + grain_samples
        if end > out_len:
            break
        out[out_pos:end] += grain
        out_norm[out_pos:end] += window
        read_pos += hop_samples
        out_pos += hop_samples

    out_norm = np.maximum(out_norm, 1e-8)
    actual_len = min(out_pos + grain_samples, out_len)
    out = (out[:actual_len] / out_norm[:actual_len]).astype(np.float32)
    return np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)


# ========== Grain Scatter ==========


def grain_scatter(
    y: np.ndarray, sr: int, scatter_amount: float = 0.5,
    grain_ms: float = 40, hop_ms: float = 10, seed: int = 42,
) -> np.ndarray:
    """
    Randomize grain positions and add occasional stutters.
    Scatter intensity varies over time via internal LFO.

    Args:
        y: Input audio (float32)
        sr: Sample rate
        scatter_amount: Overall scatter intensity (0..1)
        grain_ms / hop_ms: Grain and hop size in ms
        seed: Random seed

    Returns:
        Scattered audio (float32)
    """
    if scatter_amount <= 0.01:
        return y.copy()

    rng = np.random.default_rng(seed)
    n = len(y)
    grain_samples = int(grain_ms * sr / 1000)
    hop_samples = int(hop_ms * sr / 1000)
    window = np.hanning(grain_samples).astype(np.float32)

    scatter_env = generate_wandering_lfo(
        n, sr, center=0.5, wander_range=0.5, lfo_speed=0.5,
        num_harmonics=3, seed=seed + 10,
    )
    scatter_env = np.clip(scatter_env, 0.0, 1.0) * scatter_amount

    out = np.zeros(n + grain_samples * 4, dtype=np.float64)
    out_norm = np.zeros_like(out)
    read_pos = 0
    write_pos = 0

    while read_pos + grain_samples <= n and write_pos + grain_samples < len(out):
        center = min(read_pos + grain_samples // 2, n - 1)
        local_scatter = float(scatter_env[center])

        if rng.random() < local_scatter:
            max_offset = int(local_scatter * grain_samples * 3)
            offset = rng.integers(-max_offset, max_offset + 1)
            actual_read = max(0, min(n - grain_samples, read_pos + offset))
        else:
            actual_read = read_pos

        grain = y[actual_read:actual_read + grain_samples].copy() * window
        repeats = 1
        if rng.random() < local_scatter * 0.4:
            repeats = rng.integers(2, 4)

        for r in range(repeats):
            wp = write_pos + r * (hop_samples // 2)
            if wp + grain_samples >= len(out):
                break
            out[wp:wp + grain_samples] += grain
            out_norm[wp:wp + grain_samples] += window

        read_pos += hop_samples
        write_pos += hop_samples

    out_norm = np.maximum(out_norm, 1e-8)
    return peak_norm((out / out_norm)[:n].astype(np.float32), 0.95)


# ========== Consolidated Voice Processing Pipeline (v2) ==========


def process_voice(
    in_wav: str,
    out_wav: str,
    # Pitch (granular wandering)
    center_pitch: float = -9.5,
    pitch_wander_range: float = 4.0,
    pitch_lfo_speed: float = 0.4,
    # Formant
    formant_shift: float = 0.0,
    # Rumble layers
    sub_oct_mix: float = 0.55,
    rumble_mix: float = 0.25,
    rumble_base_hz: float = 55.0,
    drive: float = 0.55,
    xover_hz: float = 280.0,
    # Scatter
    scatter_amount: float = 0.5,
    # Speed
    speed: float = 1.0,
    # Output format
    out_sample_rate: int = 48000,
    out_channels: int = 2,
    out_sample_format: str = "s16",
    # Misc
    seed: int = 42,
) -> None:
    """
    Consolidated voice processing pipeline (v2).

    Optimized to use only 2 ffmpeg subprocess calls:
      1. ffmpeg #1: input → 16kHz mono + optional formant shift
      2. numpy:     granular pitch (main+sub) → rumble layers → scatter
      3. ffmpeg #2: post-FX + speed change + final format conversion

    Args:
        in_wav: Input WAV file path (any format from TTS)
        out_wav: Output WAV file path (tinyplay-compatible)
        center_pitch: Center pitch shift in semitones (e.g., -9.5)
        pitch_wander_range: Pitch wander ± in semitones (e.g., 4.0)
        pitch_lfo_speed: Pitch LFO speed in Hz (e.g., 0.4)
        formant_shift: Formant shift in semitones (0 = no shift)
        sub_oct_mix: Sub-octave layer mix (0..1)
        rumble_mix: Synthetic rumble noise mix (0..1)
        rumble_base_hz: Base frequency for rumble (Hz)
        drive: Soft-clipping drive (0..1)
        xover_hz: Crossover frequency (Hz)
        scatter_amount: Grain scatter intensity (0..1, 0=off)
        speed: Playback speed (0.5..2.0)
        out_sample_rate: Output sample rate (default 48000)
        out_channels: Output channels (default 2)
        out_sample_format: Output format (default s16)
        seed: Random seed (different seed = different character)
    """
    sr = 16000
    tmp_16k = str(WORKDIR / "_v2_16k.wav")
    tmp_numpy_out = str(WORKDIR / "_v2_numpy_out.wav")

    # ---- STEP 1: ffmpeg — input → 16kHz mono (+ formant) ----
    #
    # IMPORTANT: M5Stack's librubberband crashes (SIGABRT / Bad converter number)
    # when two rubberband filters are chained in a single ffmpeg call.
    # So we split into separate ffmpeg invocations.

    do_formant = abs(formant_shift) > 0.5 and ffmpeg_has_filter("rubberband")

    if do_formant:
        tmp_formant_pass1 = str(WORKDIR / "_v2_formant_p1.wav")
        fwd_ratio = 2 ** (formant_shift / 12.0)
        inv_ratio = 2 ** (-formant_shift / 12.0)

        logger.info(
            f"[process_voice] Step 1/3: 16kHz mono + formant({formant_shift:+.1f}st) [2 ffmpeg calls]"
        )

        # Pass 1: 16kHz mono + pitch shift by formant amount
        sh([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(in_wav), "-ac", "1", "-ar", str(sr),
            "-af", f"rubberband=pitch={fwd_ratio:.6f}:tempo=1",
            "-sample_fmt", "s16", str(tmp_formant_pass1),
        ])

        # Pass 2: pitch back, formant=preserved (separate process)
        sh([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(tmp_formant_pass1), "-ac", "1", "-ar", str(sr),
            "-af", f"rubberband=pitch={inv_ratio:.6f}:tempo=1:formant=preserved",
            "-sample_fmt", "s16", str(tmp_16k),
        ])

        # Cleanup pass 1 temp
        try:
            Path(tmp_formant_pass1).unlink(missing_ok=True)
        except Exception:
            pass

    else:
        # No formant: single ffmpeg for format conversion
        logger.info("[process_voice] Step 1/3: 16kHz mono")
        sh([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(in_wav), "-ac", "1", "-ar", str(sr),
            "-sample_fmt", "s16", str(tmp_16k),
        ])

    # ---- STEP 2: numpy — granular pitch + rumble + scatter ----

    dry = load16k(tmp_16k)
    n = len(dry)
    if n < sr * 0.2:
        raise RuntimeError(f"Audio too short after conversion: {n} samples")

    # 2a: Granular wandering pitch (main + sub)
    logger.info(
        f"[process_voice] Step 2/3: Granular pitch "
        f"center={center_pitch:+.1f}st wander=±{pitch_wander_range:.1f}st "
        f"lfo={pitch_lfo_speed:.2f}Hz | rumble | scatter={scatter_amount:.2f}"
    )

    pitch_curve = generate_wandering_lfo(
        n, sr, center=center_pitch, wander_range=pitch_wander_range,
        lfo_speed=pitch_lfo_speed, num_harmonics=4, seed=seed,
    )
    sub_curve = generate_wandering_lfo(
        n, sr, center=center_pitch - 12.0, wander_range=pitch_wander_range,
        lfo_speed=pitch_lfo_speed, num_harmonics=4, seed=seed,
    )

    main = granular_pitch_shift(dry, sr, pitch_curve, grain_ms=60, hop_ms=15)
    sub = granular_pitch_shift(dry, sr, sub_curve, grain_ms=60, hop_ms=15)

    min_n = min(len(dry), len(main), len(sub))
    dry, main, sub = dry[:min_n], main[:min_n], sub[:min_n]

    # 2b: Rumble layers
    low_main = butter_filter(main, sr, "lowpass", 420, order=4)
    sub_lp_hz = float(min(700.0, max(220.0, rumble_base_hz * 6.0)))
    low_sub = butter_filter(sub, sr, "lowpass", sub_lp_hz, order=4)
    gate = envelope_follower(main, sr=sr, attack_ms=6, release_ms=180, power=1.05)
    low_sub = low_sub * gate

    noise = make_rumble_noise(
        main, sr, base_hz=rumble_base_hz, amount=rumble_mix, seed=seed,
    )

    low_bus = low_main + float(sub_oct_mix) * low_sub + noise
    low_bus = tanh_drive(low_bus, drive)

    high_voice = butter_filter(main, sr, "highpass", xover_hz, order=4)
    low_rumble = butter_filter(low_bus, sr, "lowpass", xover_hz, order=4)

    mix = high_voice + low_rumble
    mix = mix - float(np.mean(mix))
    mix = peak_norm(mix, 0.95)

    # 2c: Grain scatter
    if scatter_amount > 0.01:
        mix = grain_scatter(mix, sr, scatter_amount=scatter_amount, seed=seed)

    write16k(tmp_numpy_out, mix)

    # ---- STEP 3: ffmpeg #2 — post-FX + speed + final format ----

    af_chain = [
        "aecho=0.8:0.85:120|240:0.25|0.18",
        "equalizer=f=140:t=q:w=1.1:g=3",
        "acompressor=threshold=0.18:ratio=4:attack=15:release=260:makeup=1.5",
        "alimiter=limit=0.97",
    ]

    if abs(speed - 1.0) > 0.01:
        af_chain.append(atempo_chain(speed))

    logger.info(
        f"[process_voice] Step 3/3: Post-FX"
        + (f" + speed={speed:.2f}x" if abs(speed - 1.0) > 0.01 else "")
        + f" → {out_sample_rate}Hz {out_channels}ch {out_sample_format}"
    )

    sh([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(tmp_numpy_out),
        "-af", ",".join(af_chain),
        "-ar", str(out_sample_rate),
        "-ac", str(out_channels),
        "-sample_fmt", out_sample_format,
        str(out_wav),
    ])

    # Cleanup
    for tmp in [tmp_16k, tmp_numpy_out]:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass

    logger.info(f"[process_voice] Done: {out_wav}")


# ========== Legacy Functions (backward compatibility) ==========


def pitch_shift_ffmpeg_16k(
    in_wav_16k: str, out_wav_16k: str,
    semitone_steps: float, method: str = "auto",
) -> None:
    """Legacy pitch shift. New code should use granular_pitch_shift()."""
    sr = 16000
    ratio = 2 ** (semitone_steps / 12.0)

    if method == "auto":
        methods = []
        if ffmpeg_has_filter("rubberband"):
            methods.append("rubberband")
        methods.append("asetrate")
    else:
        methods = [method]

    last_err = None
    for m in methods:
        if m == "rubberband":
            af = f"rubberband=pitch={ratio:.6f}:tempo=1"
        elif m == "asetrate":
            factor = ratio
            atempo = atempo_chain(1.0 / factor)
            af = ",".join([f"asetrate={sr*factor:.3f}", atempo, f"aresample={sr}"])
        else:
            raise ValueError(f"Unknown method: {m}")
        try:
            sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(in_wav_16k), "-ac", "1", "-ar", "16000",
                "-af", af, str(out_wav_16k)])
            return
        except subprocess.CalledProcessError as e:
            last_err = e
            logger.warning(f"[pitch_shift] method '{m}' failed -> trying fallback ...")
            continue
    if last_err is not None:
        raise last_err
    raise RuntimeError("pitch_shift_ffmpeg_16k failed unexpectedly")


def rumble_layered(in_wav_16k: str, out_wav_16k: str, **kwargs) -> None:
    """Legacy. New code should use process_voice()."""
    sr = 16000
    pitch_steps = kwargs.get("pitch_steps", -6.0)
    sub_oct_mix = kwargs.get("sub_oct_mix", 0.55)
    rumble_mix = kwargs.get("rumble_mix", 0.25)
    rumble_base_hz = kwargs.get("rumble_base_hz", 55.0)
    drive = kwargs.get("drive", 0.55)
    xover_hz = kwargs.get("xover_hz", 280.0)
    seed = kwargs.get("seed", 42)

    dry = load16k(in_wav_16k)
    main_ps = str(WORKDIR / "_r2_main.wav")
    sub_ps = str(WORKDIR / "_r2_sub.wav")
    pitch_shift_ffmpeg_16k(in_wav_16k, main_ps, pitch_steps, method="auto")
    pitch_shift_ffmpeg_16k(in_wav_16k, sub_ps, pitch_steps - 12.0, method="auto")
    main = load16k(main_ps)
    sub = load16k(sub_ps)
    n = min(len(dry), len(main), len(sub))
    if n < sr * 0.2:
        raise RuntimeError(f"audio too short: n={n}")
    dry, main, sub = dry[:n], main[:n], sub[:n]
    low_main = butter_filter(main, sr, "lowpass", 420, order=4)
    sub_lp_hz = float(min(700.0, max(220.0, rumble_base_hz * 6.0)))
    low_sub = butter_filter(sub, sr, "lowpass", sub_lp_hz, order=4)
    gate = envelope_follower(main, sr=sr, attack_ms=6, release_ms=180, power=1.05)
    low_sub = low_sub * gate
    noise = make_rumble_noise(main, sr, base_hz=rumble_base_hz, amount=rumble_mix, seed=seed)
    low_bus = low_main + float(sub_oct_mix) * low_sub + noise
    low_bus = tanh_drive(low_bus, drive)
    high_voice = butter_filter(main, sr, "highpass", xover_hz, order=4)
    low_rumble = butter_filter(low_bus, sr, "lowpass", xover_hz, order=4)
    mix = high_voice + low_rumble
    mix = mix - float(np.mean(mix))
    mix = peak_norm(mix, 0.95)
    write16k(out_wav_16k, mix)


def rumble_layered_with_fx(in_wav_16k: str, out_wav_16k: str, **kwargs) -> None:
    """Legacy. New code should use process_voice()."""
    tmp = str(WORKDIR / "_tmp_r3_base.wav")
    rumble_layered(in_wav_16k, tmp, **kwargs)
    af = ",".join([
        "aecho=0.8:0.85:120|240:0.25|0.18",
        "equalizer=f=140:t=q:w=1.1:g=3",
        "acompressor=threshold=0.18:ratio=4:attack=15:release=260:makeup=1.5",
        "alimiter=limit=0.97",
    ])
    ffmpeg_apply_filter(tmp, out_wav_16k, af)


# ========== Logging ==========

logger.info(f"FFmpeg has rubberband: {ffmpeg_has_filter('rubberband')}")
logger.info(f"FFmpeg has asubboost: {ffmpeg_has_filter('asubboost')}")
