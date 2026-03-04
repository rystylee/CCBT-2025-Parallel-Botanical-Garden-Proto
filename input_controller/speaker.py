"""
スピーカー出力 — WAVファイル保存 + 再生

指定フォルダにWAVを出力し、aplay / ffplay / mpv 等で再生。
"""
import asyncio, os, time
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger


class SpeakerOutput:
    def __init__(self, wav_dir: str = "./output_wav",
                 player: str = "aplay", player_args: list = None):
        self.wav_dir = Path(wav_dir)
        self.wav_dir.mkdir(parents=True, exist_ok=True)
        self.player = player
        self.player_args = player_args or []
        self._proc: Optional[asyncio.subprocess.Process] = None
        logger.info(f"Speaker: dir={self.wav_dir}, player={self.player}")

    def save_wav(self, audio: np.ndarray, sr: int = 16000,
                 prefix: str = "mic") -> str:
        """numpy配列 → WAVファイル保存"""
        import soundfile as sf
        ts = int(time.time() * 1000)
        path = self.wav_dir / f"{prefix}_{ts}.wav"
        sf.write(str(path), audio, sr)
        logger.info(f"Saved: {path}")
        return str(path)

    async def play_wav(self, wav_path: str):
        """非同期WAV再生"""
        if not os.path.exists(wav_path):
            logger.error(f"WAV not found: {wav_path}")
            return
        cmd = [self.player] + self.player_args + [wav_path]
        logger.info(f"Playing: {' '.join(cmd)}")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            self._proc = proc
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.warning(f"Player exit {proc.returncode}: "
                               f"{stderr.decode()[:100]}")
        except FileNotFoundError:
            logger.error(f"Player not found: {self.player}")
        except Exception as e:
            logger.error(f"Playback error: {e}")
        finally:
            self._proc = None

    def stop(self):
        if self._proc:
            self._proc.terminate()
