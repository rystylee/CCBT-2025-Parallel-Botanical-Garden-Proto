"""
Audio effects module for TTS processing — Accumulating Ghosts pipeline.

Each voice segment leaves a lingering dark spectral trace that
accumulates into an evolving harmonic cloud. Inspired by the
sound design of Jóhann Jóhannsson's "Heptapod B" from Arrival.

Processing chain:
  1. Segment voice by energy → per-segment bloom
  2. Each segment spawns a spectral ghost (smooth phase freeze)
  3. Ghosts accumulate with long decay, darkening progressively
  4. Gap fills via spectral morph of adjacent segments
  5. Schroeder algorithmic reverb (replaces FFmpeg aecho)
  6. Mastering: tape saturation → multiband warmth → soft-knee compression
  7. Stereo decorrelation via Haas effect

All processing at native sample rate (44.1kHz). No downsampling.

Based on: https://github.com/obake2ai/BI_M5_QwenSoftPrefix
"""

import math
import shlex
import subprocess
import wave
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


# ========== Native WAV I/O (full sample rate) ==========


def load_wav_native(path: str) -> tuple:
    """Load WAV at its native sample rate → (float32 ndarray, sample_rate)."""
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        raw = wf.readframes(n)
    if sw == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"Unsupported sample width: {sw}")
    if ch > 1:
        samples = samples.reshape(-1, ch).mean(axis=1)
    samples = samples - float(np.mean(samples))
    return samples, sr


def write_wav_stereo(path: str, left: np.ndarray, right: np.ndarray, sr: int) -> None:
    """Write stereo float32 arrays → 16-bit WAV."""
    left = np.clip(np.nan_to_num(left, nan=0.0), -1.0, 1.0)
    right = np.clip(np.nan_to_num(right, nan=0.0), -1.0, 1.0)
    interleaved = np.empty(len(left) * 2, dtype=np.float32)
    interleaved[0::2] = left
    interleaved[1::2] = right
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes((interleaved * 32767).astype(np.int16).tobytes())


# ========== Segmentation ==========


def segment_by_energy(
    y: np.ndarray, sr: int,
    silence_threshold: float = 0.015,
    min_segment_ms: float = 40,
    min_silence_ms: float = 15,
) -> list:
    """Split audio into voiced segments based on energy."""
    frame_ms = 5
    frame_len = int(frame_ms * sr / 1000)
    hop = frame_len
    n_frames = len(y) // hop

    energy = np.array([
        np.sqrt(np.mean(y[i * hop:i * hop + frame_len] ** 2))
        for i in range(n_frames)
    ])
    voiced = energy > silence_threshold

    # Bridge very short silences
    min_sil = int(min_silence_ms / frame_ms)
    for i in range(len(voiced)):
        if not voiced[i]:
            j = i
            while j < len(voiced) and not voiced[j]:
                j += 1
            if j - i < min_sil and j < len(voiced):
                voiced[i:j] = True

    segments = []
    in_seg, seg_start = False, 0
    for i in range(len(voiced)):
        if voiced[i] and not in_seg:
            seg_start = i
            in_seg = True
        elif not voiced[i] and in_seg:
            if (i - seg_start) * frame_ms >= min_segment_ms:
                segments.append((seg_start * hop, min(i * hop + frame_len, len(y))))
            in_seg = False
    if in_seg and (n_frames - seg_start) * frame_ms >= min_segment_ms:
        segments.append((seg_start * hop, len(y)))

    return segments


def split_long_segments(
    segments: list, y: np.ndarray, sr: int, max_ms: float = 280,
) -> list:
    """Split segments longer than max_ms at energy dips."""
    max_s = int(max_ms * sr / 1000)
    result = []
    for start, end in segments:
        if end - start <= max_s:
            result.append((start, end))
            continue
        seg = y[start:end]
        fl = int(0.008 * sr)
        hp = fl // 2
        nf = max(1, (len(seg) - fl) // hp)
        energy = np.array([
            np.sqrt(np.mean(seg[i * hp:i * hp + fl] ** 2))
            for i in range(nf)
        ])
        if len(energy) > 5:
            energy = np.convolve(energy, np.ones(5) / 5, mode="same")
        n_splits = len(seg) // max_s
        if n_splits < 1:
            result.append((start, end))
            continue
        min_gap = int(0.06 * sr / hp)
        dips = sorted([
            (energy[i], i) for i in range(1, len(energy) - 1)
            if energy[i] <= energy[i - 1] and energy[i] <= energy[i + 1]
        ])
        chosen = []
        for _, fi in dips:
            if not any(abs(fi - c) < min_gap for c in chosen):
                chosen.append(fi)
                if len(chosen) >= n_splits:
                    break
        chosen.sort()
        pts = [start] + [start + f * hp for f in chosen] + [end]
        for i in range(len(pts) - 1):
            if pts[i + 1] - pts[i] > int(0.03 * sr):
                result.append((pts[i], pts[i + 1]))
    return result


# ========== Smooth Spectral Processing ==========


def spectral_freeze_smooth(
    segment: np.ndarray, sr: int, duration_samples: int, seed: int = 0,
) -> np.ndarray:
    """
    Spectral freeze with smooth evolving phase (not random noise).

    Uses slowly drifting sinusoidal phase for each bin. Sounds like
    a sustained resonance, not white noise.
    """
    rng = np.random.default_rng(seed)
    if len(segment) < 128:
        return np.zeros(duration_samples, dtype=np.float32)

    nperseg = min(2048, len(segment))
    noverlap = nperseg * 3 // 4
    hop = nperseg - noverlap
    f, _, Zxx = signal.stft(segment, fs=sr, nperseg=nperseg, noverlap=noverlap)

    avg_mag = np.mean(np.abs(Zxx), axis=1)
    n_frames = max(2, duration_samples // hop + 2)

    # Smooth phase: natural frequency-based advancement + slow drift
    out_phase = np.zeros((len(f), n_frames), dtype=np.float64)
    out_mag = np.tile(avg_mag[:, np.newaxis], (1, n_frames))

    for k in range(len(f)):
        base_advance = 2 * np.pi * f[k] * hop / sr
        drift_speed = 0.5 + 1.0 * rng.random()
        drift = rng.standard_normal(n_frames).cumsum() * 0.02 * drift_speed
        out_phase[k, :] = (
            rng.random() * 2 * np.pi + base_advance * np.arange(n_frames) + drift
        )
        # Subtle magnitude modulation for organic movement
        mod_speed = 0.2 + 0.3 * rng.random()
        mod_depth = 0.08 + 0.08 * rng.random()
        mod = 1.0 + mod_depth * np.sin(
            2 * np.pi * mod_speed * np.arange(n_frames) * hop / sr
            + rng.random() * 2 * np.pi
        )
        out_mag[k, :] *= mod

    _, ghost = signal.istft(
        out_mag * np.exp(1j * out_phase), fs=sr,
        nperseg=nperseg, noverlap=noverlap,
    )
    ghost = ghost.astype(np.float32)
    if len(ghost) > duration_samples:
        ghost = ghost[:duration_samples]
    elif len(ghost) < duration_samples:
        ghost = np.pad(ghost, (0, duration_samples - len(ghost)))
    return ghost


def morph_ghost_smooth(
    seg_a: np.ndarray, seg_b: np.ndarray,
    sr: int, duration: int, seed: int = 0,
) -> np.ndarray:
    """Crossfade morph between spectral ghosts of two segments."""
    ga = spectral_freeze_smooth(seg_a, sr, duration, seed=seed)
    gb = spectral_freeze_smooth(seg_b, sr, duration, seed=seed + 77)
    t = np.linspace(0, 1, duration).astype(np.float32)
    s_curve = 0.5 - 0.5 * np.cos(np.pi * t)
    return ga * (1 - s_curve) + gb * s_curve


def gentle_darkfilter(
    y: np.ndarray, sr: int, cutoff: float = 500, resonance: float = 0.3,
) -> np.ndarray:
    """
    Gentle 2nd-order lowpass with slight resonance.
    Applied twice for -24dB/oct slope. Musical, not surgical.
    """
    Q = 0.707 + resonance
    w0 = 2 * np.pi * cutoff / sr
    alpha = np.sin(w0) / (2 * Q)
    b0 = (1 - np.cos(w0)) / 2
    b1 = 1 - np.cos(w0)
    b2 = (1 - np.cos(w0)) / 2
    a0 = 1 + alpha
    a1 = -2 * np.cos(w0)
    a2 = 1 - alpha
    b = np.array([b0 / a0, b1 / a0, b2 / a0])
    a = np.array([1.0, a1 / a0, a2 / a0])
    out = signal.lfilter(b, a, y).astype(np.float32)
    out = signal.lfilter(b, a, out).astype(np.float32)
    return out


# ========== Schroeder Algorithmic Reverb ==========


def schroeder_reverb(
    y: np.ndarray, sr: int,
    room_size: float = 0.82, damping: float = 0.45,
    wet: float = 0.22, predelay_ms: float = 15,
) -> np.ndarray:
    """
    Schroeder reverb: 4 parallel comb filters → 2 series allpass filters.
    Far more natural than FFmpeg aecho.
    """
    n = len(y)

    # Predelay
    pd = int(predelay_ms * sr / 1000)
    y_delayed = np.zeros(n, dtype=np.float32)
    if pd < n:
        y_delayed[pd:] = y[:n - pd]

    # Comb filters (prime-number-based delays)
    comb_delays_ms = [29.7, 37.1, 41.1, 43.7]
    comb_gains = [room_size * g for g in [0.805, 0.827, 0.783, 0.764]]

    comb_outputs = []
    for delay_ms, gain in zip(comb_delays_ms, comb_gains):
        delay = max(1, int(delay_ms * sr / 1000))
        buf = np.zeros(n, dtype=np.float64)
        lp_state = 0.0
        for i in range(n):
            fb = buf[i - delay] if i >= delay else 0.0
            lp_state = fb * (1 - damping) + lp_state * damping
            buf[i] = float(y_delayed[i]) + gain * lp_state
            buf[i] = max(-2.0, min(2.0, buf[i]))
        comb_outputs.append(buf.astype(np.float32))

    comb_sum = np.sum(comb_outputs, axis=0).astype(np.float32) / len(comb_outputs)

    # Allpass filters (diffusion)
    allpass_delays_ms = [5.0, 1.7]
    allpass_gain = 0.7
    ap_out = comb_sum.copy()

    for ap_delay_ms in allpass_delays_ms:
        delay = max(1, int(ap_delay_ms * sr / 1000))
        buf_x = ap_out.copy()
        buf_y = np.zeros(n, dtype=np.float64)
        g = allpass_gain
        for i in range(n):
            x_delayed = buf_x[i - delay] if i >= delay else 0.0
            y_delayed_val = buf_y[i - delay] if i >= delay else 0.0
            buf_y[i] = -g * float(buf_x[i]) + float(x_delayed) + g * float(y_delayed_val)
            buf_y[i] = max(-2.0, min(2.0, buf_y[i]))
        ap_out = buf_y.astype(np.float32)

    return (1 - wet) * y + wet * ap_out


# ========== Mastering Chain ==========


def tape_saturation(y: np.ndarray, drive: float = 0.3) -> np.ndarray:
    """Tape-style soft saturation via tanh waveshaping."""
    k = np.float32(1.0 + drive * 3.0)
    return np.tanh(k * y).astype(np.float32) / np.tanh(k)


def multiband_warmth(
    y: np.ndarray, sr: int,
    low_boost_db: float = 2.5, mid_cut_db: float = -1.5, air_db: float = 1.0,
) -> np.ndarray:
    """Gentle multiband EQ for warmth and presence."""
    out = y.copy()
    if abs(low_boost_db) > 0.1:
        b, a = signal.butter(2, 250, btype="low", fs=sr)
        low = signal.lfilter(b, a, y).astype(np.float32)
        out = out + low * (10 ** (low_boost_db / 20) - 1)
    if abs(mid_cut_db) > 0.1:
        b, a = signal.butter(2, [1000, 3000], btype="bandpass", fs=sr)
        mid = signal.lfilter(b, a, y).astype(np.float32)
        out = out + mid * (10 ** (mid_cut_db / 20) - 1)
    if abs(air_db) > 0.1 and sr > 16000:
        air_freq = min(8000, sr * 0.4)
        b, a = signal.butter(1, air_freq, btype="high", fs=sr)
        air = signal.lfilter(b, a, y).astype(np.float32)
        out = out + air * (10 ** (air_db / 20) - 1)
    return np.nan_to_num(out.astype(np.float32), nan=0.0)


def soft_knee_compressor(
    y: np.ndarray, sr: int,
    threshold_db: float = -16, ratio: float = 2.5,
    attack_ms: float = 25, release_ms: float = 350,
) -> np.ndarray:
    """Soft-knee compressor for transparent dynamics control."""
    threshold = 10 ** (threshold_db / 20)
    att = math.exp(-1.0 / (max(1, attack_ms) * 0.001 * sr))
    rel = math.exp(-1.0 / (max(1, release_ms) * 0.001 * sr))

    env = np.zeros(len(y), dtype=np.float32)
    prev = 0.0
    for i in range(len(y)):
        v = abs(y[i])
        a = att if v > prev else rel
        prev = a * prev + (1 - a) * v
        env[i] = prev

    gain = np.ones(len(y), dtype=np.float32)
    for i in range(len(y)):
        level = env[i] + 1e-9
        if level > threshold:
            over_db = 20 * np.log10(level / threshold)
            gain_db = over_db / ratio - over_db
            gain[i] = 10 ** (gain_db / 20)

    b, a = signal.butter(1, 30, btype="low", fs=sr)
    gain = signal.lfilter(b, a, gain).astype(np.float32)

    compressed = y * gain
    makeup = threshold / (np.sqrt(np.mean(compressed ** 2)) + 1e-9) * 0.3
    return compressed * min(makeup, 4.0)


def create_stereo(
    mono: np.ndarray, sr: int, width: float = 0.25,
) -> tuple:
    """Create subtle stereo via Haas-style decorrelation."""
    n = len(mono)
    delay = int(0.0005 * sr)

    right = np.zeros(n, dtype=np.float32)
    right[delay:] = mono[:n - delay]

    b, a = signal.butter(1, 6000, btype="low", fs=sr)
    right = signal.lfilter(b, a, right).astype(np.float32) * 0.95

    mid = 0.5 * (mono + right)
    side = 0.5 * (mono - right) * width

    return mid + side, mid - side


# ========== Accumulating Ghosts Voice Pipeline (v3) ==========


def process_voice(
    in_wav: str,
    out_wav: str,
    # --- Ghost accumulation ---
    ghost_linger_s: float = 2.5,
    ghost_level: float = 0.42,
    ghost_cutoff_start: float = 550,
    ghost_cutoff_decay: float = 12,
    ghost_resonance: float = 0.3,
    # --- Segmentation ---
    silence_threshold: float = 0.015,
    min_segment_ms: float = 40,
    max_segment_ms: float = 280,
    # --- Per-segment bloom ---
    bloom_attack_ms: float = 25,
    bloom_release_ms: float = 60,
    # --- Gap fill ---
    gap_fill_level: float = 0.25,
    gap_fill_cutoff: float = 500,
    # --- Reverb ---
    reverb_room_size: float = 0.82,
    reverb_damping: float = 0.45,
    reverb_wet: float = 0.22,
    reverb_predelay_ms: float = 15,
    # --- Mastering ---
    saturation_drive: float = 0.20,
    low_boost_db: float = 2.5,
    mid_cut_db: float = -1.5,
    air_boost_db: float = 1.0,
    comp_threshold_db: float = -16,
    comp_ratio: float = 2.5,
    # --- Stereo ---
    stereo_width: float = 0.25,
    # --- Global bloom ---
    global_attack_s: float = 0.5,
    global_release_s: float = 0.4,
    # --- Voice / ghost balance ---
    voice_level: float = 0.58,
    # --- Output format ---
    out_sample_rate: int = 48000,
    out_channels: int = 2,
    out_sample_format: str = "s16",
    # --- Misc ---
    seed: int = 42,
) -> None:
    """
    Accumulating Ghosts voice processing pipeline (v3).

    Each voice segment spawns a spectral ghost that lingers and
    accumulates into an evolving harmonic cloud. All processing
    at native sample rate with proper algorithmic reverb and mastering.

    Pipeline:
      1. Load at native SR (44.1kHz from MeloTTS)
      2. Segment by energy → per-segment bloom
      3. Each segment → smooth spectral freeze ghost (2.5s linger)
      4. Ghosts accumulate, each progressively darker
      5. Gap fills via smooth spectral morph of adjacent segments
      6. Mix voice + ghosts + gap fills
      7. Tape saturation → Schroeder reverb → multiband EQ → compressor
      8. Stereo decorrelation → output

    Args:
        in_wav: Input WAV file path (from TTS)
        out_wav: Output WAV file path
        ghost_linger_s: How long each ghost lingers (seconds)
        ghost_level: Ghost layer volume relative to voice peaks
        ghost_cutoff_start: Initial dark filter cutoff (Hz)
        ghost_cutoff_decay: Cutoff reduction per segment (Hz)
        ghost_resonance: Dark filter resonance (0-1)
        ... (see parameter list for full documentation)
        seed: Random seed for spectral phase generation
    """
    # ---- STEP 1: Load at native sample rate ----

    y, sr = load_wav_native(in_wav)
    n = len(y)
    if n < sr * 0.1:
        raise RuntimeError(f"Audio too short: {n} samples ({n / sr:.2f}s)")

    logger.info(
        f"[ghost] Step 1/4: Loaded {n} samples at {sr}Hz ({n / sr:.2f}s)"
    )

    # ---- STEP 2: Segment and bloom ----

    segs = segment_by_energy(y, sr, silence_threshold, min_segment_ms)
    segs = split_long_segments(segs, y, sr, max_segment_ms)

    voice = np.zeros(n, dtype=np.float32)
    for s, e in segs:
        seg = y[s:e].copy()
        seg_n = len(seg)
        a = max(1, int(bloom_attack_ms * sr / 1000))
        r = max(1, int(bloom_release_ms * sr / 1000))
        if a + r > seg_n:
            ratio = seg_n / (a + r + 1)
            a, r = max(1, int(a * ratio)), max(1, int(r * ratio))
        h = max(0, seg_n - a - r)
        env = np.concatenate([
            np.linspace(0, 1, a) ** 0.4,
            np.ones(h),
            np.linspace(1, 0, r) ** 0.4,
        ])[:seg_n]
        voice[s:e] = seg * env

    logger.info(
        f"[ghost] Step 2/4: {len(segs)} segments, bloom {bloom_attack_ms}/{bloom_release_ms}ms"
    )

    # ---- STEP 3: Accumulating ghost layer ----

    ghost_layer = np.zeros(n, dtype=np.float32)
    linger_samples = int(ghost_linger_s * sr)

    for i, (s, e) in enumerate(segs):
        seg = y[s:e]
        ghost_len = min(linger_samples, n - s)

        ghost = spectral_freeze_smooth(seg, sr, ghost_len, seed=seed + i * 17)

        cutoff = max(200, ghost_cutoff_start - i * ghost_cutoff_decay)
        ghost = gentle_darkfilter(ghost, sr, cutoff=cutoff, resonance=ghost_resonance)

        # Envelope: quick attack, long exponential decay
        env = np.ones(ghost_len, dtype=np.float32)
        attack_samples = min(int(0.035 * sr), ghost_len // 4)
        env[:attack_samples] = np.linspace(0, 1, attack_samples) ** 0.5
        decay_start = min(e - s, ghost_len)
        if decay_start < ghost_len:
            remaining = ghost_len - decay_start
            env[decay_start:] = np.exp(-np.linspace(0, 3.5, remaining))

        ghost *= env
        end = min(s + ghost_len, n)
        ghost_layer[s:end] += ghost[:end - s]

    # Normalize ghost level relative to voice
    if np.max(np.abs(ghost_layer)) > 1e-6:
        ghost_layer *= (
            ghost_level * np.max(np.abs(voice))
            / (np.max(np.abs(ghost_layer)) + 1e-9)
        )

    # ---- Gap fills with smooth ghost morphs ----

    gap_fill = np.zeros(n, dtype=np.float32)
    for i in range(len(segs) - 1):
        gs, ge = segs[i][1], segs[i + 1][0]
        gl = ge - gs
        if gl <= 0:
            continue
        ctx = min(
            int(0.12 * sr),
            segs[i][1] - segs[i][0],
            segs[i + 1][1] - segs[i + 1][0],
        )
        g = morph_ghost_smooth(
            y[segs[i][1] - ctx:segs[i][1]],
            y[segs[i + 1][0]:segs[i + 1][0] + ctx],
            sr, gl, seed + i * 13,
        )
        g = gentle_darkfilter(g, sr, gap_fill_cutoff, 0.2)
        fd = min(int(0.025 * sr), gl // 3)
        if fd > 1:
            g[:fd] *= np.linspace(0, 1, fd)
            g[-fd:] *= np.linspace(1, 0, fd)
        gap_fill[gs:ge] = g

    grms = np.sqrt(np.mean(gap_fill ** 2)) + 1e-9
    vrms = np.sqrt(np.mean(voice ** 2)) + 1e-9
    gap_fill *= (vrms * gap_fill_level) / grms

    logger.info(
        f"[ghost] Step 3/4: Ghosts accumulated "
        f"(linger={ghost_linger_s}s, level={ghost_level})"
    )

    # ---- STEP 4: Mix + mastering ----

    # Global bloom
    ga = int(global_attack_s * sr)
    gr = int(global_release_s * sr)
    if ga + gr > n:
        ratio = n / (ga + gr + 1)
        ga, gr = int(ga * ratio), int(gr * ratio)
    gh = max(0, n - ga - gr)
    bloom = np.concatenate([
        np.linspace(0, 1, max(1, ga)) ** 0.7,
        np.ones(gh),
        np.linspace(1, 0, max(1, gr)) ** 0.5,
    ]).astype(np.float32)[:n]

    raw_mix = voice_level * voice + ghost_layer + gap_fill
    raw_mix *= bloom
    raw_mix = np.nan_to_num(raw_mix, nan=0.0, posinf=0.0, neginf=0.0)

    # Mastering chain
    mastered = tape_saturation(raw_mix, drive=saturation_drive)

    mastered = schroeder_reverb(
        mastered, sr,
        room_size=reverb_room_size, damping=reverb_damping,
        wet=reverb_wet, predelay_ms=reverb_predelay_ms,
    )
    mastered = np.nan_to_num(mastered, nan=0.0, posinf=0.0, neginf=0.0)

    mastered = multiband_warmth(
        mastered, sr,
        low_boost_db=low_boost_db, mid_cut_db=mid_cut_db, air_db=air_boost_db,
    )

    mastered = soft_knee_compressor(
        mastered, sr,
        threshold_db=comp_threshold_db, ratio=comp_ratio,
    )

    # Final gentle glue saturation
    mastered = tape_saturation(mastered, drive=0.08)
    mastered = peak_norm(mastered, 0.90)

    logger.info(
        f"[ghost] Step 4/4: Mastered → {out_sample_rate}Hz {out_channels}ch"
    )

    # ---- Output ----

    if out_channels >= 2 and stereo_width > 0:
        left, right = create_stereo(mastered, sr, width=stereo_width)
        tmp_stereo = str(WORKDIR / "_v3_stereo.wav")
        write_wav_stereo(tmp_stereo, left, right, sr)
    else:
        tmp_stereo = str(WORKDIR / "_v3_mono.wav")
        write16k(tmp_stereo, mastered)  # reuse for mono output

    # Final format conversion (sample rate + format only, no audio effects)
    sh([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", tmp_stereo,
        "-ar", str(out_sample_rate),
        "-ac", str(out_channels),
        "-sample_fmt", out_sample_format,
        str(out_wav),
    ])

    try:
        Path(tmp_stereo).unlink(missing_ok=True)
    except Exception:
        pass

    logger.info(f"[ghost] Done: {out_wav}")


# ========== Legacy Rumble Voice Pipeline (v2, switchable) ==========


def process_voice_rumble(
    in_wav: str,
    out_wav: str,
    center_pitch: float = -9.5,
    pitch_wander_range: float = 4.0,
    pitch_lfo_speed: float = 0.4,
    formant_shift: float = 0.0,
    sub_oct_mix: float = 0.55,
    rumble_mix: float = 0.25,
    rumble_base_hz: float = 55.0,
    drive: float = 0.55,
    xover_hz: float = 280.0,
    scatter_amount: float = 0.5,
    speed: float = 1.0,
    out_sample_rate: int = 48000,
    out_channels: int = 2,
    out_sample_format: str = "s16",
    seed: int = 42,
) -> None:
    """
    Legacy rumble voice processing pipeline (v2).
    Granular pitch shift + sub-octave + rumble + FFmpeg post-FX.
    Kept for backward compatibility and A/B comparison.
    """
    sr = 16000
    tmp_16k = str(WORKDIR / "_v2_16k.wav")
    tmp_numpy_out = str(WORKDIR / "_v2_numpy_out.wav")

    # Step 1: convert to 16kHz mono (+ optional formant)
    do_formant = abs(formant_shift) > 0.5

    if do_formant and RUBBERBAND_WORKS:
        tmp_fp1 = str(WORKDIR / "_v2_formant_p1.wav")
        fwd = 2 ** (formant_shift / 12.0)
        inv = 2 ** (-formant_shift / 12.0)
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(in_wav), "-ac", "1", "-ar", str(sr),
            "-af", f"rubberband=pitch={fwd:.6f}:tempo=1",
            "-sample_fmt", "s16", str(tmp_fp1)])
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(tmp_fp1), "-ac", "1", "-ar", str(sr),
            "-af", f"rubberband=pitch={inv:.6f}:tempo=1:formant=preserved",
            "-sample_fmt", "s16", str(tmp_16k)])
        try:
            Path(tmp_fp1).unlink(missing_ok=True)
        except Exception:
            pass
    elif do_formant:
        gain = float(np.clip(formant_shift, -8.0, 8.0))
        eq = [f"equalizer=f=300:t=q:w=0.8:g={-gain:.1f}",
              f"equalizer=f=1800:t=q:w=1.0:g={gain:.1f}",
              f"equalizer=f=4500:t=q:w=1.2:g={gain*0.5:.1f}"]
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(in_wav), "-ac", "1", "-ar", str(sr),
            "-af", ",".join(eq), "-sample_fmt", "s16", str(tmp_16k)])
    else:
        sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(in_wav), "-ac", "1", "-ar", str(sr),
            "-sample_fmt", "s16", str(tmp_16k)])

    # Step 2: granular pitch + rumble + scatter
    dry = load16k(tmp_16k)
    n = len(dry)
    if n < sr * 0.2:
        raise RuntimeError(f"Audio too short: {n} samples")

    logger.info(f"[rumble] Granular pitch={center_pitch:+.1f}st wander=±{pitch_wander_range:.1f}st")

    pc = generate_wandering_lfo(n, sr, center=center_pitch,
                                wander_range=pitch_wander_range,
                                lfo_speed=pitch_lfo_speed, seed=seed)
    sc = generate_wandering_lfo(n, sr, center=center_pitch - 12.0,
                                wander_range=pitch_wander_range,
                                lfo_speed=pitch_lfo_speed, seed=seed)

    main = granular_pitch_shift(dry, sr, pc, grain_ms=60, hop_ms=15)
    sub = granular_pitch_shift(dry, sr, sc, grain_ms=60, hop_ms=15)

    min_n = min(len(dry), len(main), len(sub))
    dry, main, sub = dry[:min_n], main[:min_n], sub[:min_n]

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
    mix -= float(np.mean(mix))
    mix = peak_norm(mix, 0.95)

    if scatter_amount > 0.01:
        mix = grain_scatter(mix, sr, scatter_amount=scatter_amount, seed=seed)

    write16k(tmp_numpy_out, mix)

    # Step 3: FFmpeg post-FX
    af_chain = [
        "aecho=0.8:0.85:120|240:0.25|0.18",
        "equalizer=f=140:t=q:w=1.1:g=3",
        "acompressor=threshold=0.18:ratio=4:attack=15:release=260:makeup=1.5",
        "alimiter=limit=0.97",
    ]
    if abs(speed - 1.0) > 0.01:
        af_chain.append(atempo_chain(speed))

    sh(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(tmp_numpy_out), "-af", ",".join(af_chain),
        "-ar", str(out_sample_rate), "-ac", str(out_channels),
        "-sample_fmt", out_sample_format, str(out_wav)])

    for tmp in [tmp_16k, tmp_numpy_out]:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass

    logger.info(f"[rumble] Done: {out_wav}")


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
        if RUBBERBAND_WORKS:
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


# ========== Runtime capability detection ==========


def _test_rubberband_runtime() -> bool:
    """
    Test if rubberband actually works at runtime.

    ffmpeg -filters may report rubberband as available even when
    the underlying libsamplerate is broken (e.g. M5Stack aarch64).
    We test by running a tiny real conversion.
    """
    if not ffmpeg_has_filter("rubberband"):
        return False

    test_in = str(WORKDIR / "_rb_test_in.wav")
    test_out = str(WORKDIR / "_rb_test_out.wav")

    try:
        # Generate a tiny 0.1s silent WAV
        silence = np.zeros(1600, dtype=np.float32)  # 0.1s at 16kHz
        sf.write(test_in, silence, 16000)

        # Try a simple rubberband pitch shift
        result = sh([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", test_in, "-af", "rubberband=pitch=1.1:tempo=1",
            "-ac", "1", "-ar", "16000", test_out,
        ], check=False)

        return result.returncode == 0
    except Exception:
        return False
    finally:
        for f in [test_in, test_out]:
            try:
                Path(f).unlink(missing_ok=True)
            except Exception:
                pass


RUBBERBAND_WORKS = _test_rubberband_runtime()
logger.info(f"FFmpeg has rubberband filter: {ffmpeg_has_filter('rubberband')}")
logger.info(f"Rubberband runtime test: {'OK' if RUBBERBAND_WORKS else 'FAILED (will use fallbacks)'}")
