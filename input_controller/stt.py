"""
Speech-to-Text (Whisper) — モデル共有マルチチャンネル並列処理

Whisperモデルを1つロードし、ThreadPoolExecutorで4ch並列文字起こし。
faster-whisper優先、openai-whisper fallback。
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Optional

import numpy as np
from loguru import logger


class SharedWhisperSTT:

    def __init__(self, model_size: str = "base", language: str = "ja",
                 device: str = "cpu", max_workers: int = 4):
        self.model_size = model_size
        self.language = language
        self.device = device
        self._model = None
        self._is_faster = False
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = asyncio.Lock()  # モデル初期化用

    def _ensure_model(self):
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
            logger.info(f"Loading faster-whisper '{self.model_size}' on {self.device}")
            ct = "int8" if self.device == "cpu" else "float16"
            self._model = WhisperModel(self.model_size, device=self.device,
                                       compute_type=ct)
            self._is_faster = True
            logger.info("faster-whisper loaded")
        except ImportError:
            logger.warning("faster-whisper not found → openai-whisper fallback")
            import whisper
            self._model = whisper.load_model(self.model_size, device=self.device)
            self._is_faster = False

    def transcribe_one(self, audio: np.ndarray) -> str:
        """1チャンネル分の文字起こし (blocking)"""
        self._ensure_model()
        try:
            if self._is_faster:
                segs, _ = self._model.transcribe(
                    audio, language=self.language,
                    beam_size=5, vad_filter=True,
                )
                return "".join(s.text for s in segs).strip()
            else:
                r = self._model.transcribe(
                    audio, language=self.language,
                    fp16=(self.device != "cpu"),
                )
                return r["text"].strip()
        except Exception as e:
            logger.error(f"STT error: {e}")
            return ""

    async def transcribe_channels(self, channels: Dict[int, np.ndarray]) -> Dict[int, str]:
        """複数チャンネルを並列に文字起こし"""
        self._ensure_model()
        loop = asyncio.get_event_loop()
        futures = {
            ch: loop.run_in_executor(self._executor, self.transcribe_one, audio)
            for ch, audio in channels.items()
        }
        results = {}
        for ch, fut in futures.items():
            try:
                text = await fut
                if text:
                    results[ch] = text
                    logger.info(f"  ch{ch} STT: '{text[:60]}'")
            except Exception as e:
                logger.error(f"  ch{ch} STT failed: {e}")
        return results
