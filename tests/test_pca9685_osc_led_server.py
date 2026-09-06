"""Hardware-free regression tests: python -B -m unittest discover -s tests -p test_pca9685_osc_led_server.py -v

Run both real entry points with simulated time, OSC callbacks and PWM writes.
No sockets, physical I2C devices or background threads are opened.
"""

import importlib.util
import io
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


def load_server():
    stubs = {name: ModuleType(name) for name in (
        "smbus2", "pythonosc", "pythonosc.dispatcher", "pythonosc.osc_server"
    )}
    stubs["smbus2"].SMBus = object
    stubs["pythonosc.dispatcher"].Dispatcher = object
    stubs["pythonosc.osc_server"].ThreadingOSCUDPServer = object
    spec = importlib.util.spec_from_file_location(
        "_led_server_under_test", Path(__file__).resolve().parent.parent / "pca9685_osc_led_server_v2.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {**stubs, spec.name: module}):
        spec.loader.exec_module(module)
    return module


led = load_server()


class EndSimulation(Exception):
    pass


class ServerTests(unittest.TestCase):
    modes = ("cli", "embedded")

    def run_scenario(self, mode, events, **settings):
        clock = SimpleNamespace(now=0.0)
        handlers = {}
        threads = []
        writes = {}
        events = iter(events)

        class Dispatcher:
            def map(self, address, callback):
                handlers[address] = callback

        class Server:
            def __init__(self, *args):
                pass

            def serve_forever(self):
                pass

            def shutdown(self):
                pass

        class Thread:
            def __init__(self, target, **kwargs):
                self.target = target
                threads.append(self)

            def start(self):
                pass

        class PWM:
            connected = True
            bus_id = 1

            def __init__(self, cfg):
                pass

            def set_duty(self, duty):
                writes[clock.now] = duty
                return True

            def off(self):
                pass

            def disconnect(self):
                self.connected = False

        def sleep(dt):
            try:
                clock.now, messages = next(events)
            except StopIteration:
                raise EndSimulation()
            for address, values in messages:
                handlers[address](address, *values)

        fake_time = SimpleNamespace(
            monotonic=lambda: clock.now,
            time=lambda: 1_000_000.0 - clock.now,  # Wall clock moves backwards.
            sleep=sleep,
        )
        with ExitStack() as stack:
            stack.enter_context(patch.object(led, "Dispatcher", Dispatcher))
            stack.enter_context(patch.object(led, "ThreadingOSCUDPServer", Server))
            stack.enter_context(patch.object(led, "PCA9685Manager", PWM))
            stack.enter_context(patch.object(led.threading, "Thread", Thread))
            stack.enter_context(patch.object(led.signal, "signal"))
            stack.enter_context(patch.object(led, "time", fake_time))
            stack.enter_context(redirect_stdout(io.StringIO()))
            with self.assertRaises(EndSimulation):
                if mode == "cli":
                    argv = ["pca9685_osc_led_server.py"]
                    for key, value in settings.items():
                        flag = "max" if key == "max_brightness" else key.replace("_", "-")
                        argv.extend(["--" + flag, str(value)])
                    stack.enter_context(patch.object(sys, "argv", argv))
                    led.main()
                else:
                    led.start_led_server({"led_control": {
                        "enabled": True, "pca9685": settings,
                    }})
                    threads[-1].target()
        return writes

    def test_led_timeout_boundary_and_resume(self):
        for mode in self.modes:
            with self.subTest(mode=mode):
                output = self.run_scenario(mode, [
                    (1.0, [("/led", (0.5,))]),
                    (61.0, []), (180.999, []), (181.0, []),
                    (182.0, [("/led", (0.75,))]),
                    (361.999, []), (362.0, []),
                ])
                self.assertAlmostEqual(output[1.0], 0.217637640824031)
                self.assertEqual(output[61.0], output[1.0])
                self.assertEqual(output[180.999], output[1.0])
                self.assertEqual(output[181.0], 0.0)
                self.assertAlmostEqual(output[182.0], 0.75 ** 2.2)
                self.assertEqual(output[361.999], output[182.0])
                self.assertEqual(output[362.0], 0.0)

    def test_led_timeout_does_not_cancel_fresh_external_input(self):
        for mode in self.modes:
            with self.subTest(mode=mode):
                output = self.run_scenario(mode, [
                    (1.0, [("/led", (1.0,)), ("/bri_ex", (0.5,)), ("/led_ratio", (0.5,))]),
                    (180.0, [("/bri_ex", (0.5,))]),
                    (181.0, []), (360.0, []),
                ], gamma=1.0)
                self.assertEqual(output[180.0], 0.75)
                self.assertEqual(output[181.0], 0.25)
                self.assertEqual(output[360.0], 0.0)

    def test_led_stream_does_not_keep_external_override_alive(self):
        for mode in self.modes:
            with self.subTest(mode=mode):
                output = self.run_scenario(mode, [
                    (1.0, [("/bri_ex", (1.0,)), ("/led_ratio", (0.0,))]),
                    (180.0, [("/led", (0.25,))]),
                    (181.0, []),
                    (182.0, [("/led_ratio", (0.0,))]),
                ], gamma=1.0)
                self.assertEqual(output[180.0], 1.0)
                self.assertEqual(output[181.0], 0.25)
                self.assertEqual(output[182.0], 1.0)

    def test_each_external_address_renews_external_deadline(self):
        for mode in self.modes:
            for address in ("/bri_ex", "/led/bri_ex", "/led_ratio", "/led/ratio"):
                with self.subTest(mode=mode, address=address):
                    value = 1.0 if "bri_ex" in address else 0.0
                    output = self.run_scenario(mode, [
                        (1.0, [("/bri_ex", (1.0,)), ("/led_ratio", (0.0,))]),
                        (50.0, [(address, (0, value))]),
                        (181.0, []), (229.999, []), (230.0, []),
                    ])
                    self.assertEqual(output[181.0], 1.0)
                    self.assertEqual(output[229.999], 1.0)
                    self.assertEqual(output[230.0], 0.0)

    def test_invalid_or_wrong_channel_led_does_not_renew(self):
        for mode in self.modes:
            for values in ((), ("0",), (2.0,), (float("nan"),), (float("inf"),), (1, 0.5)):
                with self.subTest(mode=mode, values=values):
                    output = self.run_scenario(mode, [
                        (1.0, [("/led", (1.0,))]),
                        (180.0, [("/led", values)]), (181.0, []),
                    ])
                    self.assertEqual(output[180.0], 1.0)
                    self.assertEqual(output[181.0], 0.0)

    def test_invalid_external_input_does_not_renew(self):
        for mode in self.modes:
            with self.subTest(mode=mode):
                output = self.run_scenario(mode, [
                    (1.0, [("/bri_ex", (1.0,)), ("/led_ratio", (0.0,))]),
                    (180.0, [("/led/bri_ex", ("1",)), ("/led/ratio", (1, 0.0))]),
                    (181.0, []),
                ])
                self.assertEqual(output[180.0], 1.0)
                self.assertEqual(output[181.0], 0.0)

    def test_timeout_bypasses_fade_and_on_does_not_renew(self):
        for mode in self.modes:
            with self.subTest(mode=mode):
                output = self.run_scenario(mode, [
                    (1.0, [("/led", (1.0,))]),
                    (180.0, [("/led/on", ())]),
                    (181.0, []), (182.0, [("/led/on", ())]),
                ], fade=1000.0)
                self.assertGreater(output[180.0], 0.0)
                self.assertEqual(output[181.0], 0.0)
                self.assertEqual(output[182.0], 0.0)

    def test_configurable_independent_timeouts(self):
        for mode in self.modes:
            with self.subTest(mode=mode):
                output = self.run_scenario(mode, [
                    (1.0, [("/led", (1.0,)), ("/bri_ex", (1.0,)), ("/led_ratio", (0.5,))]),
                    (3.0, []), (5.0, []),
                ], led_timeout=2.0, external_timeout=4.0, gamma=1.0)
                self.assertEqual(output[3.0], 0.5)
                self.assertEqual(output[5.0], 0.0)

    def test_gamma_zero_output_and_max_cap(self):
        for mode in self.modes:
            for gamma in (0.5, 1.0, 2.2):
                with self.subTest(mode=mode, gamma=gamma):
                    output = self.run_scenario(mode, [
                        (1.0, [("/led", (1.0,))]),
                        (2.0, [("/led/off", ())]),
                    ], gamma=gamma, max_brightness=0.25)
                    self.assertGreater(output[1.0], 0.0)
                    self.assertLessEqual(output[1.0], 0.25)
                    self.assertEqual(output[2.0], 0.0)

    def test_invalid_gamma_and_timeouts_rejected_before_hardware(self):
        for key in ("gamma", "led_timeout", "external_timeout"):
            for value in (0.0, -1.0, float("nan"), float("inf")):
                with self.subTest(key=key, value=value):
                    with patch.object(led, "PCA9685Manager") as pwm:
                        with self.assertRaises(ValueError):
                            led.start_led_server({"led_control": {
                                "enabled": True, "pca9685": {key: value},
                            }})
                        with patch.object(sys, "argv", [
                            "server", "--" + key.replace("_", "-"), str(value),
                        ]):
                            with self.assertRaises(SystemExit):
                                led.main()
                        pwm.assert_not_called()


if __name__ == "__main__":
    unittest.main()
