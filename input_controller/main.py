"""
Input Controller メイン

Ubuntu PC (10.0.0.200) で動作:
  1) 4chマイク同時録音 → チャンネル別STT → 閾値以上ならM5送信
  2) センサーOSC受信 → バッファ → マイクと同タイミングでM5送信
  3) WAVファイル保存 + スピーカー再生

Usage:
  python -m input_controller                          # デフォルト
  python -m input_controller --config input_config.json
  python -m input_controller --list-devices           # デバイス一覧
"""
import argparse, asyncio, signal, time
from loguru import logger

from .config import InputControllerConfig, load_default_config, load_config_from_json
from .audio_backend import create_backend
from .mic import MultiChannelRecorder
from .stt import SharedWhisperSTT
from .sensor_receiver import SensorOscReceiver
from .sender import BiInputSender
from .soft_prefix import make_random_sp_b64, sensor_to_sp_b64
from .speaker import SpeakerOutput


class InputController:
    def __init__(self, config: InputControllerConfig):
        self.cfg = config
        self.running = False

        # --- オーディオバックエンド ---
        self.backend = create_backend(config.audio_backend)
        self.backend.setup(config.audio_device, config.mic_channels,
                           config.mic_sample_rate)

        # --- マイク ---
        self.mic = MultiChannelRecorder(
            backend=self.backend,
            channels=config.mic_channels,
            silence_threshold=config.mic_silence_threshold,
        )

        # --- STT ---
        self.stt = SharedWhisperSTT(
            model_size=config.stt_model,
            language=config.stt_language,
            device=config.stt_device,
            max_workers=config.stt_max_workers,
        )

        # --- センサー ---
        self.sensor = SensorOscReceiver(port=config.osc_receive_port)
        for rule in config.sensor_rules:
            self.sensor.register_address(rule.osc_address)

        # --- 送信 ---
        self.sender = BiInputSender()

        # --- スピーカー ---
        self.speaker = SpeakerOutput(
            wav_dir=config.speaker_wav_dir,
            player=config.speaker_player,
            player_args=config.speaker_player_args,
        ) if config.speaker_enabled else None

    async def start(self):
        self.running = True
        logger.info("=" * 55)
        logger.info("  CCBT Input Controller v3")
        logger.info("=" * 55)
        logger.info(f"Audio backend : {self.cfg.audio_backend}")
        logger.info(f"Audio device  : {self.cfg.audio_device or '(default)'}")
        logger.info(f"Mic channels  : {self.cfg.mic_channels}")
        logger.info(f"Record sec    : {self.cfg.mic_record_sec}")
        logger.info(f"Interval sec  : {self.cfg.mic_interval_sec}")
        logger.info(f"STT model     : {self.cfg.stt_model} ({self.cfg.stt_device})")
        logger.info(f"STT workers   : {self.cfg.stt_max_workers}")
        logger.info(f"Mic rules     : {len(self.cfg.mic_rules)}")
        logger.info(f"Sensor rules  : {len(self.cfg.sensor_rules)}")
        logger.info(f"Speaker       : {self.cfg.speaker_enabled}")

        transport = await self.sensor.start()

        try:
            await self._main_loop()
        except asyncio.CancelledError:
            pass
        finally:
            transport.close()
            logger.info("Controller stopped")

    def stop(self):
        self.running = False
        logger.info("Stop requested")

    async def _main_loop(self):
        """
        メインサイクル:
          1. 4ch録音
          2. チャンネル別STT (ThreadPool並列)
          3. 閾値チェック → M5送信
          4. 同タイミングでセンサーも送信
          5. WAV保存 + スピーカー再生
          6. インターバル待機
        """
        cycle = 0
        while self.running:
            cycle += 1
            t0 = time.time()
            logger.info(f"--- cycle {cycle} ---")

            # 1. 録音
            ch_audio = await self.mic.record_and_split_async(self.cfg.mic_record_sec)

            # 2. STT
            ch_texts = {}
            if ch_audio:
                ch_texts = await self.stt.transcribe_channels(ch_audio)

            # 3. マイク → M5
            for rule in self.cfg.mic_rules:
                text = ch_texts.get(rule.channel, "")
                if len(text) >= rule.min_text_len:
                    sp = make_random_sp_b64(self.cfg.soft_prefix_p,
                                            self.cfg.soft_prefix_h)
                    logger.info(f"[mic ch{rule.channel}] → "
                                f"{len(rule.targets)} devs: '{text[:50]}'")
                    self.sender.send_to_targets(rule.targets, text, sp, 0)
                elif text:
                    logger.debug(f"[mic ch{rule.channel}] below threshold "
                                 f"({len(text)}<{rule.min_text_len})")

            # 4. センサー → M5 (同タイミング)
            for rule in self.cfg.sensor_rules:
                s_text = self.sensor.buffer.format_for_text(rule.osc_address)
                if s_text:
                    fv = self.sensor.buffer.get_float_value(rule.osc_address)
                    sp = (sensor_to_sp_b64(fv, self.cfg.soft_prefix_p,
                                           self.cfg.soft_prefix_h)
                          if fv is not None
                          else make_random_sp_b64(self.cfg.soft_prefix_p,
                                                  self.cfg.soft_prefix_h))
                    logger.info(f"[sensor {rule.osc_address}] → "
                                f"{len(rule.targets)} devs: '{s_text}'")
                    self.sender.send_to_targets(rule.targets, s_text, sp, 0)

            # 5. スピーカー
            if self.speaker and ch_audio:
                for ch, audio in ch_audio.items():
                    wav = self.speaker.save_wav(audio, self.cfg.mic_sample_rate,
                                                prefix=f"mic_ch{ch}")
                    asyncio.create_task(self.speaker.play_wav(wav))

            # 6. インターバル
            elapsed = time.time() - t0
            wait = max(0.0, self.cfg.mic_interval_sec - elapsed)
            if wait > 0:
                await asyncio.sleep(wait)


# --- CLI ---

def parse_args():
    p = argparse.ArgumentParser(description="CCBT Input Controller v3")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--list-devices", action="store_true",
                   help="List audio devices and exit")
    return p.parse_args()


async def async_main():
    args = parse_args()

    if args.list_devices:
        for name in ("sounddevice", "pyaudio", "alsa_raw"):
            try:
                b = create_backend(name)
                b.setup("", 1, 16000)
                print(f"\n=== {name} ===")
                print(b.list_devices())
            except Exception as e:
                print(f"\n=== {name} === (unavailable: {e})")
        return

    cfg = load_config_from_json(args.config) if args.config else load_default_config()
    ctrl = InputController(cfg)

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, ctrl.stop)

    await ctrl.start()


def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
