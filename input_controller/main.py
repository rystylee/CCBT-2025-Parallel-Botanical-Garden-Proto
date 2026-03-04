"""
Input Controller - Ubuntu PC (10.0.0.200) -> BI devices
"""
import argparse, asyncio, base64, random, signal, struct
from loguru import logger
from .config import InputControllerConfig, load_default_config, load_config_from_json
from .stt import SpeechToText
from .sensor import (BaseSensorReader, SerialSensorReader, DummySensorReader,
                     sensor_to_soft_prefix_b64, f32_to_bf16_u16)
from .sender import BiInputSender

VALS = [0.0, 1e-4, 1e-3, 1e-2]

def make_random_sp_b64(p, h):
    val = random.choice(VALS)
    u16 = f32_to_bf16_u16(val)
    raw = struct.pack("<H", u16) * (p * h)
    return base64.b64encode(raw).decode("ascii")

class InputController:
    def __init__(self, config: InputControllerConfig, use_dummy=False):
        self.config = config
        self.sender = BiInputSender()
        self.running = False
        self.stt = SpeechToText(
            model_size=config.stt_model, language=config.stt_language,
            device=config.stt_device, sample_rate=config.audio_sample_rate,
            channels=config.audio_channels)
        self.sensors: list[BaseSensorReader] = []
        for rule in config.sensor_rules:
            if use_dummy:
                self.sensors.append(DummySensorReader())
            elif rule.sensor_type == "serial":
                self.sensors.append(SerialSensorReader(
                    port=config.sensor_serial_port, baud=config.sensor_baud_rate))
            else:
                self.sensors.append(DummySensorReader())

    async def start(self):
        self.running = True
        logger.info("=== Input Controller Starting ===")
        for s in self.sensors:
            try: await s.connect()
            except Exception as e: logger.error(f"Sensor connect: {e}")
        tasks = []
        for i, rule in enumerate(self.config.voice_rules):
            tasks.append(asyncio.create_task(self._voice_loop(rule, i)))
        for i, rule in enumerate(self.config.sensor_rules):
            sen = self.sensors[i] if i < len(self.sensors) else DummySensorReader()
            tasks.append(asyncio.create_task(self._sensor_loop(rule, sen, i)))
        logger.info(f"Started {len(tasks)} pipelines")
        try: await asyncio.gather(*tasks)
        except asyncio.CancelledError: pass

    def stop(self):
        self.running = False

    async def _voice_loop(self, rule, lid=0):
        logger.info(f"[Voice-{lid}] targets={[t.ip for t in rule.targets]}")
        while self.running:
            try:
                text = await self.stt.record_and_transcribe()
                if text:
                    sp = make_random_sp_b64(self.config.soft_prefix_p,
                                            self.config.soft_prefix_h)
                    logger.info(f"[Voice-{lid}] sending: {text[:40]}")
                    self.sender.send_to_targets(rule.targets, text, sp, 0)
            except Exception as e:
                logger.error(f"[Voice-{lid}] {e}")
            await asyncio.sleep(rule.interval_sec)

    async def _sensor_loop(self, rule, sensor, lid=0):
        logger.info(f"[Sensor-{lid}] targets={[t.ip for t in rule.targets]}")
        while self.running:
            try:
                val = await sensor.read_value()
                if val is not None:
                    sp = sensor_to_soft_prefix_b64(
                        val, p=self.config.soft_prefix_p, h=self.config.soft_prefix_h)
                    text = f"[sensor:{val:.3f}]"
                    self.sender.send_to_targets(rule.targets, text, sp, 0)
            except Exception as e:
                logger.error(f"[Sensor-{lid}] {e}")
            await asyncio.sleep(rule.interval_sec)

def parse_args():
    p = argparse.ArgumentParser(description="CCBT Input Controller")
    p.add_argument("--config", type=str, default=None)
    p.add_argument("--dummy-sensor", action="store_true")
    return p.parse_args()

async def async_main():
    args = parse_args()
    cfg = load_config_from_json(args.config) if args.config else load_default_config()
    ctrl = InputController(cfg, use_dummy=args.dummy_sensor)
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, ctrl.stop)
    await ctrl.start()
    for s in ctrl.sensors: await s.disconnect()

def main():
    asyncio.run(async_main())

if __name__ == "__main__":
    main()
