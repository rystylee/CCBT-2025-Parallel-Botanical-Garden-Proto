"""
マルチチャンネルマイク録音

AudioBackend経由で4ch同時録音 → チャンネルごとにnumpy配列で分離。
RME Fireface UC/UCX, Behringer, 汎用USBマイクいずれでも動作。
"""
import asyncio
from typing import Dict, Optional

import numpy as np
from loguru import logger

from .audio_backend import AudioBackend


class MultiChannelRecorder:
    """
    マルチチャンネル同時録音

    1回のセッションで全チャンネルを録音し、
    無音判定でチャンネルごとに振り分ける。
    """

    def __init__(self, backend: AudioBackend, channels: int = 4,
                 silence_threshold: float = 0.01):
        self.backend = backend
        self.channels = channels
        self.silence_threshold = silence_threshold

    def record_and_split(self, duration_sec: float) -> Optional[Dict[int, np.ndarray]]:
        """
        全チャンネル同時録音 → チャンネル分離

        Returns:
            {ch_index: np.ndarray(float32, mono)} — 無音チャンネルは除外
        """
        logger.info(f"Recording {self.channels}ch x {duration_sec}s ...")
        raw = self.backend.record_blocking(duration_sec)
        if raw is None:
            return None

        # shape check: (frames, channels)
        if raw.ndim == 1:
            # mono fallback
            raw = raw.reshape(-1, 1)

        actual_ch = raw.shape[1]
        result = {}
        for ch in range(min(self.channels, actual_ch)):
            ch_audio = raw[:, ch]
            rms = np.sqrt(np.mean(ch_audio ** 2))
            logger.debug(f"  ch{ch}: rms={rms:.5f}")
            if rms >= self.silence_threshold:
                result[ch] = ch_audio
            else:
                logger.debug(f"  ch{ch}: silent, skipped")

        if actual_ch < self.channels:
            logger.warning(f"Requested {self.channels}ch but device returned "
                           f"{actual_ch}ch — missing channels ignored")

        logger.info(f"Active channels: {list(result.keys())} / {self.channels}")
        return result if result else None

    async def record_and_split_async(self, duration_sec: float) -> Optional[Dict[int, np.ndarray]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.record_and_split, duration_sec)
