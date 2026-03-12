#!/usr/bin/env python3
# python3 pca9685_osc_led_server.py --port 9000

# sudo apt-get update
# sudo apt-get install -y python3-pip i2c-tools
# python3 -m pip install --user smbus2 python-osc

import argparse
import glob
import signal
import sys
import threading
import time
from dataclasses import dataclass
from typing import Optional, List

from smbus2 import SMBus
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

# ===== PCA9685 registers =====
MODE1      = 0x00
MODE2      = 0x01
PRESCALE   = 0xFE
LED0_ON_L  = 0x06

# MODE1 bits
RESTART = 1 << 7
SLEEP   = 1 << 4
AI      = 1 << 5  # Auto-Increment

# MODE2 bits
OUTDRV  = 1 << 2  # Totem-pole output driver


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def list_i2c_buses() -> List[int]:
    buses = []
    for dev in sorted(glob.glob("/dev/i2c-*")):
        try:
            buses.append(int(dev.split("-")[-1]))
        except ValueError:
            pass
    return buses


def parse_brightness_01_strict(x) -> Optional[float]:
    """
    Strict brightness parser:
      - Accept ONLY numeric (int/float) in range [0.0, 1.0]
      - Return None if invalid (non-numeric or out of range)
    """
    if isinstance(x, (int, float)):
        v = float(x)
        if 0.0 <= v <= 1.0:
            return v
        return None
    return None


def parse_osc_value_01_strict(osc_args, target_ch: int):
    """
    Returns (handled, value):
      - handled=False: ignore (no args or channel mismatch)
      - handled=True and value=None: invalid payload
      - handled=True and value=float: valid payload
    """
    if len(osc_args) == 0:
        return False, None

    if len(osc_args) == 1:
        return True, parse_brightness_01_strict(osc_args[0])

    try:
        ch = int(osc_args[0])
        if ch != target_ch:
            return False, None
        return True, parse_brightness_01_strict(osc_args[1])
    except Exception:
        return True, None


def mix_duty(bri: float, bri_ex: float, led_ratio: float) -> float:
    bri = clamp(float(bri), 0.0, 1.0)
    bri_ex = clamp(float(bri_ex), 0.0, 1.0)
    led_ratio = clamp(float(led_ratio), 0.0, 1.0)
    return clamp((led_ratio * bri) + ((1.0 - led_ratio) * bri_ex), 0.0, 1.0)


@dataclass
class PCA9685Config:
    addr: int
    osc_hz: float
    pwm_freq_hz: float
    channel: int


class PCA9685Manager:
    """
    Keeps running even if device is not present.
    Reconnects by probing I2C bus periodically.
    """

    def __init__(self, cfg: PCA9685Config):
        self.cfg = cfg
        self._bus_id: Optional[int] = None
        self._bus: Optional[SMBus] = None
        self._connected = False
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._connected

    @property
    def bus_id(self) -> Optional[int]:
        with self._lock:
            return self._bus_id

    def _close_locked(self):
        if self._bus is not None:
            try:
                self._bus.close()
            except Exception:
                pass
        self._bus = None
        self._bus_id = None
        self._connected = False

    def disconnect(self):
        with self._lock:
            self._close_locked()

    def _probe_bus(self, bus_id: int) -> bool:
        try:
            b = SMBus(bus_id)
            _ = b.read_byte_data(self.cfg.addr, MODE1)  # probe
            b.close()
            return True
        except Exception:
            try:
                b.close()
            except Exception:
                pass
            return False

    def _set_pwm_freq_locked(self, freq_hz: float):
        assert self._bus is not None
        freq_hz = clamp(freq_hz, 1.0, 2000.0)
        prescale = int(round(self.cfg.osc_hz / (4096.0 * freq_hz) - 1.0))
        prescale = int(clamp(prescale, 3, 255))

        old_mode = self._bus.read_byte_data(self.cfg.addr, MODE1)
        sleep_mode = (old_mode & ~RESTART) | SLEEP
        self._bus.write_byte_data(self.cfg.addr, MODE1, sleep_mode)
        time.sleep(0.005)

        self._bus.write_byte_data(self.cfg.addr, PRESCALE, prescale)

        # wake
        self._bus.write_byte_data(self.cfg.addr, MODE1, (old_mode & ~SLEEP) | AI)
        time.sleep(0.005)

        # restart
        self._bus.write_byte_data(self.cfg.addr, MODE1, (old_mode & ~SLEEP) | AI | RESTART)
        time.sleep(0.005)

    def _write_channel_locked(self, duty_0_1: float):
        assert self._bus is not None
        ch = self.cfg.channel
        duty = float(clamp(duty_0_1, 0.0, 1.0))
        reg = LED0_ON_L + 4 * ch

        if duty <= 0.0:
            # full off (OFF_H bit4)
            data = [0x00, 0x00, 0x00, 0x10]
        elif duty >= 1.0:
            # full on (ON_H bit4)
            data = [0x00, 0x10, 0x00, 0x00]
        else:
            off = int(round(duty * 4095.0))
            off = int(clamp(off, 1, 4095))
            data = [0x00, 0x00, off & 0xFF, (off >> 8) & 0x0F]

        self._bus.write_i2c_block_data(self.cfg.addr, reg, data)

    def try_connect(self, candidate_buses: List[int]) -> bool:
        with self._lock:
            if self._connected:
                return True

        for bus_id in candidate_buses:
            if not self._probe_bus(bus_id):
                continue

            try:
                b = SMBus(bus_id)
                _ = b.read_byte_data(self.cfg.addr, MODE1)

                # MODE2: totem-pole
                b.write_byte_data(self.cfg.addr, MODE2, OUTDRV)

                # MODE1: auto-increment enabled
                mode1 = b.read_byte_data(self.cfg.addr, MODE1)
                mode1 = (mode1 & ~SLEEP) | AI
                b.write_byte_data(self.cfg.addr, MODE1, mode1)

                with self._lock:
                    self._bus = b
                    self._bus_id = bus_id
                    self._connected = True

                # Set PWM frequency
                with self._lock:
                    self._set_pwm_freq_locked(self.cfg.pwm_freq_hz)

                # Fail-safe: start OFF
                self.set_duty(0.0)
                return True

            except Exception:
                try:
                    b.close()
                except Exception:
                    pass
                with self._lock:
                    self._close_locked()
                continue

        return False

    def set_duty(self, duty_0_1: float) -> bool:
        with self._lock:
            if not self._connected or self._bus is None:
                return False
            try:
                self._write_channel_locked(duty_0_1)
                return True
            except Exception:
                self._close_locked()
                return False

    def off(self):
        self.set_duty(0.0)


def main():
    ap = argparse.ArgumentParser(description="OSC -> PCA9685 PWM server (auto-reconnect, bri/bri_ex/led_ratio 0..1 only)")
    ap.add_argument("--listen", default="0.0.0.0", help="OSC listen IP (default 0.0.0.0)")
    ap.add_argument("--port", type=int, default=9000, help="OSC UDP port (default 9000)")
    ap.add_argument("--addr", type=lambda v: int(v, 0), default=0x40, help="PCA9685 I2C address (default 0x40)")
    ap.add_argument("--ch", type=int, default=0, help="PCA9685 channel 0..15 (default 0)")
    ap.add_argument("--bus", type=int, default=None,
                    help="固定I2Cバス番号（例: 1）。未指定なら /dev/i2c-* をスキャン")
    ap.add_argument("--freq", type=float, default=1000.0, help="PWM frequency Hz (default 1000)")
    ap.add_argument("--osc", type=float, default=25_000_000.0, help="PCA9685 oscillator Hz (default 25MHz)")
    ap.add_argument("--gamma", type=float, default=1.0, help="Gamma correction (1.0=linear, 2.2=perceptual)")
    ap.add_argument("--max", dest="max_bri", type=float, default=1.0,
                    help="Safety max brightness (0.0..1.0). Default 1.0")
    ap.add_argument("--fade", type=float, default=0.0,
                    help="Fade time seconds to reach new target (0=immediate). Default 0")
    ap.add_argument("--rate", type=float, default=100.0,
                    help="Update rate Hz for fade loop (default 100)")
    ap.add_argument("--reconnect-interval", type=float, default=2.0,
                    help="Seconds between reconnect attempts when disconnected (default 2.0)")
    ap.add_argument("--log-interval", type=float, default=5.0,
                    help="Throttle repeated identical logs in seconds (default 5.0)")
    args = ap.parse_args()

    if not (0 <= args.ch <= 15):
        raise SystemExit("--ch must be 0..15")
    if not (0.0 <= args.max_bri <= 1.0):
        raise SystemExit("--max must be in 0.0..1.0")

    cfg = PCA9685Config(
        addr=args.addr,
        osc_hz=args.osc,
        pwm_freq_hz=args.freq,
        channel=args.ch,
    )
    pwm = PCA9685Manager(cfg)

    max_bri = float(args.max_bri)

    # Shared state
    state_lock = threading.Lock()
    target = {"bri": 0.0, "bri_ex": 0.0, "led_ratio": 1.0}
    current = {"bri": 0.0}
    last_nonzero = {
        "bri": min(0.2, max_bri) if max_bri > 0 else 0.0,
        "bri_ex": 0.0,
    }
    stop = {"flag": False}

    # Log throttling
    last_log = {"t": 0.0, "msg": ""}

    def log_throttled(msg: str):
        now = time.time()
        if msg == last_log["msg"] and (now - last_log["t"]) < args.log_interval:
            return
        last_log["t"] = now
        last_log["msg"] = msg
        print(msg, flush=True)

    def candidate_buses() -> List[int]:
        if args.bus is not None:
            return [args.bus]
        return list_i2c_buses()

    def apply_output(duty_0_1: float) -> bool:
        """
        Apply max clamp + gamma, then write to PCA9685 if connected.
        """
        duty_0_1 = clamp(duty_0_1, 0.0, 1.0)
        duty_0_1 = min(duty_0_1, max_bri)
        out = (duty_0_1 ** args.gamma) if args.gamma != 1.0 else duty_0_1
        return pwm.set_duty(out)

    # ===== OSC handlers =====
    def osc_led(address, *osc_args):
        """
        Strict:
          /led <brightness_float_0_to_1>
          /led <ch:int> <brightness_float_0_to_1>  (optional)
        Out-of-range or non-numeric -> ignored (no change).
        """
        handled, bri = parse_osc_value_01_strict(osc_args, args.ch)
        if not handled:
            return
        if bri is None:
            log_throttled("[WARN] /led ignored: brightness must be float 0.0..1.0")
            return

        bri = min(bri, max_bri)

        with state_lock:
            target["bri"] = bri
            if bri > 0.0:
                last_nonzero["bri"] = bri

    def osc_bri_ex(address, *osc_args):
        handled, bri_ex = parse_osc_value_01_strict(osc_args, args.ch)
        if not handled:
            return
        if bri_ex is None:
            log_throttled("[WARN] /bri_ex ignored: brightness must be float 0.0..1.0")
            return

        bri_ex = min(bri_ex, max_bri)

        with state_lock:
            target["bri_ex"] = bri_ex
            if bri_ex > 0.0:
                last_nonzero["bri_ex"] = bri_ex

    def osc_led_ratio(address, *osc_args):
        handled, led_ratio = parse_osc_value_01_strict(osc_args, args.ch)
        if not handled:
            return
        if led_ratio is None:
            log_throttled("[WARN] /led_ratio ignored: value must be float 0.0..1.0")
            return

        with state_lock:
            target["led_ratio"] = led_ratio

    def osc_on(address, *osc_args):
        with state_lock:
            target["bri"] = last_nonzero["bri"]
            target["bri_ex"] = last_nonzero["bri_ex"]

    def osc_off(address, *osc_args):
        with state_lock:
            target["bri"] = 0.0
            target["bri_ex"] = 0.0

    def osc_toggle(address, *osc_args):
        with state_lock:
            target_duty = mix_duty(target["bri"], target["bri_ex"], target["led_ratio"])
            current_duty = mix_duty(current["bri"], target["bri_ex"], target["led_ratio"])
            if target_duty > 0.0 or current_duty > 0.0:
                target["bri"] = 0.0
                target["bri_ex"] = 0.0
            else:
                target["bri"] = last_nonzero["bri"]
                target["bri_ex"] = last_nonzero["bri_ex"]

    dispatcher = Dispatcher()
    dispatcher.map("/led", osc_led)
    dispatcher.map("/bri_ex", osc_bri_ex)
    dispatcher.map("/led/bri_ex", osc_bri_ex)
    dispatcher.map("/led_ratio", osc_led_ratio)
    dispatcher.map("/led/ratio", osc_led_ratio)
    dispatcher.map("/led/on", osc_on)
    dispatcher.map("/led/off", osc_off)
    dispatcher.map("/led/toggle", osc_toggle)

    server = ThreadingOSCUDPServer((args.listen, args.port), dispatcher)

    def server_thread():
        server.serve_forever()

    th = threading.Thread(target=server_thread, daemon=True)
    th.start()

    print("[INFO] OSC -> PCA9685 server (auto-reconnect, bri/bri_ex/led_ratio=0.0..1.0 only)")
    print(f"[INFO] OSC listen: udp://{args.listen}:{args.port}")
    print(f"[INFO] PCA9685 addr=0x{args.addr:02X} ch={args.ch} freq={args.freq}Hz gamma={args.gamma} max={max_bri:.3f}")
    print("[INFO] OSC commands:")
    print("  /led <float 0.0..1.0>")
    print("  /bri_ex <float 0.0..1.0>")
    print("  /led_ratio <float 0.0..1.0>")
    print("  /<cmd> <ch:int> <float 0.0..1.0>   (optional: /led, /bri_ex, /led_ratio)")
    print("  /led/on  /led/off  /led/toggle")
    if args.bus is not None:
        print(f"[INFO] I2C bus fixed: /dev/i2c-{args.bus}")
    else:
        print("[INFO] I2C bus scan: /dev/i2c-* (will retry while disconnected)")

    # Signal handling
    def on_signal(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    dt = 1.0 / max(10.0, float(args.rate))
    next_reconnect = 0.0
    was_connected = False

    try:
        # Start OFF
        with state_lock:
            target["bri"] = 0.0
            target["bri_ex"] = 0.0
            target["led_ratio"] = 1.0
            current["bri"] = 0.0

        while not stop["flag"]:
            now = time.time()

            # Reconnect logic
            if not pwm.connected and now >= next_reconnect:
                buses = candidate_buses()
                if not buses:
                    log_throttled("[WARN] No /dev/i2c-* found. Will retry.")
                    next_reconnect = now + args.reconnect_interval
                else:
                    ok = pwm.try_connect(buses)
                    if ok:
                        log_throttled(f"[INFO] Connected to PCA9685 on /dev/i2c-{pwm.bus_id} addr=0x{args.addr:02X}")
                        with state_lock:
                            current["bri"] = 0.0
                        was_connected = True
                    else:
                        log_throttled(f"[WARN] PCA9685 not found (addr=0x{args.addr:02X}). Retrying...")
                        next_reconnect = now + args.reconnect_interval

            # If connection dropped
            if was_connected and not pwm.connected:
                log_throttled("[WARN] PCA9685 disconnected. Will retry.")
                with state_lock:
                    current["bri"] = 0.0
                was_connected = False
                next_reconnect = now + args.reconnect_interval

            # Fade loop
            with state_lock:
                t = target["bri"]
                c = current["bri"]
                bri_ex = target["bri_ex"]
                led_ratio = target["led_ratio"]

            if args.fade <= 0.0:
                c_new = t
            else:
                step = dt / float(args.fade)
                diff = t - c
                if abs(diff) <= step:
                    c_new = t
                else:
                    c_new = c + step if diff > 0 else c - step
                c_new = clamp(c_new, 0.0, 1.0)

            duty_new = mix_duty(c_new, bri_ex, led_ratio)

            if pwm.connected:
                applied = apply_output(duty_new)
                if not applied:
                    log_throttled("[WARN] I2C write failed. Marked as disconnected; will retry.")
                    was_connected = False
                    next_reconnect = now + args.reconnect_interval
                else:
                    with state_lock:
                        current["bri"] = c_new
                    was_connected = True
            else:
                with state_lock:
                    current["bri"] = 0.0

            time.sleep(dt)

    finally:
        # Fail-safe OFF (best effort)
        try:
            if pwm.connected:
                pwm.off()
        except Exception:
            pass
        try:
            server.shutdown()
        except Exception:
            pass
        pwm.disconnect()
        print("\n[INFO] Stopped. LED OFF (best effort).")


def start_led_server(config: dict) -> None:
    """
    Start PCA9685 LED server as a daemon thread using config dict.

    Reads settings from config["led_control"] and starts the OSC server
    and I2C control loop in background threads.

    Args:
        config: Application config dict with "led_control" section
    """
    led_config = config.get("led_control", {})

    if not led_config.get("enabled", False):
        print("[LED] LED control is disabled in config")
        return

    # Extract settings from config (with defaults matching CLI defaults)
    pca_config = led_config.get("pca9685", {})
    listen_ip = "0.0.0.0"
    port = led_config.get("targets", [{}])[0].get("port", 9000)
    addr = pca_config.get("addr", 0x40)
    channel = pca_config.get("channel", 0)
    bus = pca_config.get("bus", None)
    freq = pca_config.get("freq", 1000.0)
    osc_hz = pca_config.get("osc_hz", 25_000_000.0)
    gamma = pca_config.get("gamma", 1.0)
    max_bri = pca_config.get("max_brightness", 1.0)
    fade = pca_config.get("fade", 0.0)
    rate = pca_config.get("rate", 100.0)
    reconnect_interval = pca_config.get("reconnect_interval", 2.0)
    log_interval = pca_config.get("log_interval", 5.0)

    cfg = PCA9685Config(
        addr=addr,
        osc_hz=osc_hz,
        pwm_freq_hz=freq,
        channel=channel,
    )
    pwm = PCA9685Manager(cfg)

    # Shared state
    state_lock = threading.Lock()
    target = {"bri": 0.0, "bri_ex": 0.0, "led_ratio": 1.0}
    current = {"bri": 0.0}
    last_nonzero = {
        "bri": min(0.2, max_bri) if max_bri > 0 else 0.0,
        "bri_ex": 0.0,
    }
    stop = {"flag": False}

    last_log = {"t": 0.0, "msg": ""}

    def log_throttled(msg: str):
        now = time.time()
        if msg == last_log["msg"] and (now - last_log["t"]) < log_interval:
            return
        last_log["t"] = now
        last_log["msg"] = msg
        print(msg, flush=True)

    def candidate_buses() -> List[int]:
        if bus is not None:
            return [bus]
        return list_i2c_buses()

    def apply_output(duty_0_1: float) -> bool:
        duty_0_1 = clamp(duty_0_1, 0.0, 1.0)
        duty_0_1 = min(duty_0_1, max_bri)
        out = (duty_0_1 ** gamma) if gamma != 1.0 else duty_0_1
        return pwm.set_duty(out)

    # OSC handlers
    def osc_led(address, *osc_args):
        handled, bri_val = parse_osc_value_01_strict(osc_args, channel)
        if not handled:
            return
        if bri_val is None:
            return
        bri_val = min(bri_val, max_bri)
        with state_lock:
            target["bri"] = bri_val
            if bri_val > 0.0:
                last_nonzero["bri"] = bri_val

    def osc_bri_ex(address, *osc_args):
        handled, bri_ex_val = parse_osc_value_01_strict(osc_args, channel)
        if not handled:
            return
        if bri_ex_val is None:
            return
        bri_ex_val = min(bri_ex_val, max_bri)
        with state_lock:
            target["bri_ex"] = bri_ex_val
            if bri_ex_val > 0.0:
                last_nonzero["bri_ex"] = bri_ex_val

    def osc_led_ratio(address, *osc_args):
        handled, led_ratio_val = parse_osc_value_01_strict(osc_args, channel)
        if not handled:
            return
        if led_ratio_val is None:
            return
        with state_lock:
            target["led_ratio"] = led_ratio_val

    def osc_on(address, *osc_args):
        with state_lock:
            target["bri"] = last_nonzero["bri"]
            target["bri_ex"] = last_nonzero["bri_ex"]

    def osc_off(address, *osc_args):
        with state_lock:
            target["bri"] = 0.0
            target["bri_ex"] = 0.0

    def osc_toggle(address, *osc_args):
        with state_lock:
            target_duty = mix_duty(target["bri"], target["bri_ex"], target["led_ratio"])
            current_duty = mix_duty(current["bri"], target["bri_ex"], target["led_ratio"])
            if target_duty > 0.0 or current_duty > 0.0:
                target["bri"] = 0.0
                target["bri_ex"] = 0.0
            else:
                target["bri"] = last_nonzero["bri"]
                target["bri_ex"] = last_nonzero["bri_ex"]

    dispatcher = Dispatcher()
    dispatcher.map("/led", osc_led)
    dispatcher.map("/bri_ex", osc_bri_ex)
    dispatcher.map("/led/bri_ex", osc_bri_ex)
    dispatcher.map("/led_ratio", osc_led_ratio)
    dispatcher.map("/led/ratio", osc_led_ratio)
    dispatcher.map("/led/on", osc_on)
    dispatcher.map("/led/off", osc_off)
    dispatcher.map("/led/toggle", osc_toggle)

    server = ThreadingOSCUDPServer((listen_ip, port), dispatcher)

    # Start OSC server thread
    osc_thread = threading.Thread(target=server.serve_forever, daemon=True)
    osc_thread.start()

    # Start I2C control loop thread
    def control_loop():
        dt = 1.0 / max(10.0, float(rate))
        next_reconnect = 0.0
        was_connected = False

        with state_lock:
            target["bri"] = 0.0
            target["bri_ex"] = 0.0
            target["led_ratio"] = 1.0
            current["bri"] = 0.0

        while not stop["flag"]:
            now = time.time()

            if not pwm.connected and now >= next_reconnect:
                buses = candidate_buses()
                if not buses:
                    log_throttled("[LED] No /dev/i2c-* found. Will retry.")
                    next_reconnect = now + reconnect_interval
                else:
                    ok = pwm.try_connect(buses)
                    if ok:
                        log_throttled(f"[LED] Connected to PCA9685 on /dev/i2c-{pwm.bus_id} addr=0x{addr:02X}")
                        with state_lock:
                            current["bri"] = 0.0
                        was_connected = True
                    else:
                        log_throttled(f"[LED] PCA9685 not found (addr=0x{addr:02X}). Retrying...")
                        next_reconnect = now + reconnect_interval

            if was_connected and not pwm.connected:
                log_throttled("[LED] PCA9685 disconnected. Will retry.")
                with state_lock:
                    current["bri"] = 0.0
                was_connected = False
                next_reconnect = now + reconnect_interval

            with state_lock:
                t = target["bri"]
                c = current["bri"]
                bri_ex = target["bri_ex"]
                led_ratio = target["led_ratio"]

            if fade <= 0.0:
                c_new = t
            else:
                step_size = dt / float(fade)
                diff = t - c
                if abs(diff) <= step_size:
                    c_new = t
                else:
                    c_new = c + step_size if diff > 0 else c - step_size
                c_new = clamp(c_new, 0.0, 1.0)

            duty_new = mix_duty(c_new, bri_ex, led_ratio)

            if pwm.connected:
                applied = apply_output(duty_new)
                if not applied:
                    log_throttled("[LED] I2C write failed. Will retry.")
                    was_connected = False
                    next_reconnect = now + reconnect_interval
                else:
                    with state_lock:
                        current["bri"] = c_new
                    was_connected = True
            else:
                with state_lock:
                    current["bri"] = 0.0

            time.sleep(dt)

        # Cleanup
        try:
            if pwm.connected:
                pwm.off()
        except Exception:
            pass
        try:
            server.shutdown()
        except Exception:
            pass
        pwm.disconnect()

    control_thread = threading.Thread(target=control_loop, daemon=True)
    control_thread.start()

    print(f"[LED] Started: OSC udp://{listen_ip}:{port} -> PCA9685 addr=0x{addr:02X} ch={channel}")


if __name__ == "__main__":
    sys.exit(main())