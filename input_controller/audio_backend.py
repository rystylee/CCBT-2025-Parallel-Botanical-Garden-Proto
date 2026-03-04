"""
オーディオバックエンド抽象化

どのオーディオIF (RME Fireface UC/UCX, Behringer, 汎用USB)
でも動くよう、録音処理をバックエンド差し替え可能にする。

対応バックエンド:
  - sounddevice (PortAudio) — 最も汎用的
  - pyaudio (PortAudio)     — sounddeviceの代替
  - alsa_raw (直接ALSA)     — PulseAudio/PipeWire回避

設定の audio_device 書式:
  sounddevice : デバイスindex (int) or "" (default)
  pyaudio     : デバイスindex (int) or "" (default)
  alsa_raw    : "hw:1,0" などALSAデバイス名
"""
import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Optional

import numpy as np
from loguru import logger


class AudioBackend(ABC):
    """録音バックエンド抽象クラス"""

    @abstractmethod
    def setup(self, device: str, channels: int, sample_rate: int):
        """初期化"""

    @abstractmethod
    def record_blocking(self, duration_sec: float) -> Optional[np.ndarray]:
        """
        ブロッキング録音
        Returns: (frames, channels) shape の float32 ndarray, or None
        """

    @abstractmethod
    def list_devices(self) -> str:
        """利用可能デバイス一覧 (デバッグ用)"""

    async def record_async(self, duration_sec: float) -> Optional[np.ndarray]:
        """非同期ラッパー"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.record_blocking, duration_sec)


# ---------- sounddevice バックエンド ----------

class SoundDeviceBackend(AudioBackend):
    """sounddevice (PortAudio) ベース"""

    def setup(self, device: str, channels: int, sample_rate: int):
        import sounddevice as sd
        self.sd = sd
        self.channels = channels
        self.sample_rate = sample_rate
        # device: "" → None (default), 数字文字列 → int
        if device == "":
            self.device_id = None
        else:
            try:
                self.device_id = int(device)
            except ValueError:
                # デバイス名で検索
                self.device_id = device
        logger.info(f"[sounddevice] device={self.device_id}, "
                     f"ch={channels}, sr={sample_rate}")

    def record_blocking(self, duration_sec: float) -> Optional[np.ndarray]:
        try:
            frames = int(self.sample_rate * duration_sec)
            audio = self.sd.rec(
                frames=frames,
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                device=self.device_id,
            )
            self.sd.wait()
            return audio  # shape (frames, channels)
        except Exception as e:
            logger.error(f"[sounddevice] record error: {e}")
            return None

    def list_devices(self) -> str:
        import sounddevice as sd
        return str(sd.query_devices())


# ---------- PyAudio バックエンド ----------

class PyAudioBackend(AudioBackend):
    """PyAudio (PortAudio) ベース"""

    def setup(self, device: str, channels: int, sample_rate: int):
        import pyaudio
        self.pa = pyaudio.PyAudio()
        self.channels = channels
        self.sample_rate = sample_rate
        self.chunk = 1024
        self.device_index = int(device) if device else None
        logger.info(f"[pyaudio] device={self.device_index}, "
                     f"ch={channels}, sr={sample_rate}")

    def record_blocking(self, duration_sec: float) -> Optional[np.ndarray]:
        import pyaudio
        try:
            stream = self.pa.open(
                format=pyaudio.paFloat32,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.chunk,
            )
            total_frames = int(self.sample_rate * duration_sec)
            frames = []
            remaining = total_frames
            while remaining > 0:
                n = min(self.chunk, remaining)
                data = stream.read(n, exception_on_overflow=False)
                frames.append(np.frombuffer(data, dtype=np.float32))
                remaining -= n
            stream.stop_stream()
            stream.close()
            audio = np.concatenate(frames)
            return audio.reshape(-1, self.channels)
        except Exception as e:
            logger.error(f"[pyaudio] record error: {e}")
            return None

    def list_devices(self) -> str:
        lines = []
        for i in range(self.pa.get_device_count()):
            info = self.pa.get_device_info_by_index(i)
            lines.append(f"  [{i}] {info['name']}  "
                         f"in={info['maxInputChannels']} "
                         f"out={info['maxOutputChannels']} "
                         f"sr={info['defaultSampleRate']}")
        return "\n".join(lines)


# ---------- ALSA Raw バックエンド ----------

class AlsaRawBackend(AudioBackend):
    """
    ALSA直接アクセス (PulseAudio/PipeWire バイパス)
    RME Fireface UCなどPipeWireで問題が出る場合の最終手段。
    subprocess + arecord を使用。
    """

    def setup(self, device: str, channels: int, sample_rate: int):
        self.device = device or "hw:0,0"
        self.channels = channels
        self.sample_rate = sample_rate
        logger.info(f"[alsa_raw] device={self.device}, "
                     f"ch={channels}, sr={sample_rate}")

    def record_blocking(self, duration_sec: float) -> Optional[np.ndarray]:
        import subprocess, io, wave, struct
        cmd = [
            "arecord",
            "-D", self.device,
            "-f", "S16_LE",
            "-r", str(self.sample_rate),
            "-c", str(self.channels),
            "-d", str(int(duration_sec)),
            "-t", "wav",
            "-q",           # quiet
            "-",            # stdout
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=duration_sec + 5)
            if result.returncode != 0:
                logger.error(f"[alsa_raw] arecord failed: {result.stderr.decode()[:200]}")
                return None
            wav_data = io.BytesIO(result.stdout)
            with wave.open(wav_data, "rb") as wf:
                n_frames = wf.getnframes()
                raw = wf.readframes(n_frames)
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                return samples.reshape(-1, self.channels)
        except subprocess.TimeoutExpired:
            logger.error("[alsa_raw] arecord timeout")
            return None
        except Exception as e:
            logger.error(f"[alsa_raw] error: {e}")
            return None

    def list_devices(self) -> str:
        import subprocess
        try:
            r = subprocess.run(["arecord", "-l"], capture_output=True, text=True)
            return r.stdout
        except Exception:
            return "(arecord not found)"


# ---------- ファクトリ ----------

def create_backend(name: str) -> AudioBackend:
    backends = {
        "sounddevice": SoundDeviceBackend,
        "pyaudio": PyAudioBackend,
        "alsa_raw": AlsaRawBackend,
    }
    cls = backends.get(name)
    if cls is None:
        raise ValueError(f"Unknown audio backend: {name!r}. "
                         f"Available: {list(backends.keys())}")
    return cls()
