import argparse
import asyncio
import json

from loguru import logger

from app import AppController
from bi import BIController

# from pca9685_osc_led_server_v2 import start_led_server
from pca9685_osc_led_server_v2 import start_led_server
from utils import load_network_config

DEVICE_ID_FILE = "/etc/ccbt-device-id"
NETWORK_INTERFACES = "/etc/network/interfaces"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_path", type=str, default="config/config.json")
    parser.add_argument(
        "--device-id", type=int, default=None, help="Device ID (e.g. 61). If omitted, auto-detected from network config"
    )
    parser.add_argument(
        "--raw-audio", action="store_true", help="Debug mode: skip FFmpeg processing, save raw WAV, play with aplay"
    )
    parser.add_argument(
        "--listen-host", type=str, default=None, help="Override OSC listen address (e.g. 0.0.0.0 for test env)"
    )
    return parser.parse_args()


def resolve_lang_from_device_id(device_id: int) -> str:
    """Resolve language from the last digit of device ID.

    1-2: ja, 3-4: en, 5-6: fr, 7-8: fa, 9-0: ar
    """
    last_digit = device_id % 10
    mapping = {
        # 1: "ja",
        # 2: "ja",
        # 3: "en",
        # 4: "en",
        # 5: "fr",
        # 6: "fr",
        # 7: "fa",
        # 8: "fa",
        # 9: "ar",
        # 0: "ar",
        1: "en",
        2: "ja",
        3: "fr",
        4: "ja",
        5: "fa",
        6: "ja",
        7: "ar",
        8: "ja",
        9: "ja",
        0: "ja",
    }
    return mapping[last_digit]


def resolve_device_id(cli_value: int | None) -> int:
    """Resolve device ID from CLI argument, /etc/ccbt-device-id, or /etc/network/interfaces."""
    if cli_value is not None:
        return cli_value

    # Try /etc/ccbt-device-id
    try:
        with open(DEVICE_ID_FILE, "r") as f:
            device_id = int(f.read().strip())
            logger.info(f"Read device_id={device_id} from {DEVICE_ID_FILE}")
            return device_id
    except (FileNotFoundError, ValueError):
        pass

    # Try /etc/network/interfaces (parse "address 10.0.0.XX")
    try:
        with open(NETWORK_INTERFACES, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("address 10.0.0."):
                    device_id = int(line.split(".")[-1])
                    logger.info(f"Read device_id={device_id} from {NETWORK_INTERFACES}")
                    return device_id
    except (FileNotFoundError, ValueError):
        pass

    raise SystemExit(
        "Error: Could not determine device_id.\n"
        "  - No --device-id argument\n"
        f"  - {DEVICE_ID_FILE} not found\n"
        f"  - No 'address 10.0.0.X' in {NETWORK_INTERFACES}\n"
        "Run: uv run python main.py --device-id <ID>"
    )


async def async_main():
    opt = parse_args()

    with open(opt.config_path, mode="r", encoding="utf-8") as f:
        config = json.load(f)

    if opt.raw_audio:
        config.setdefault("audio", {})["debug_raw_audio"] = True
        logger.info("RAW AUDIO DEBUG MODE enabled: skipping FFmpeg, saving raw WAVs to /tmp/bi_debug/")

    # Device ID from CLI argument or /etc/ccbt-device-id
    device_id = resolve_device_id(opt.device_id)
    csv_path = config.get("network", {}).get("csv_path", "config/networks.csv")

    logger.info(f"Loading network config for device ID {device_id} from {csv_path}")
    network_config = load_network_config(csv_path)

    # Get IP address and targets from CSV
    ip_address = network_config.get_ip_address(device_id)
    if ip_address is None:
        raise ValueError(f"Device ID {device_id} has no IP address in CSV")

    targets = network_config.resolve_targets(device_id, port=config.get("osc", {}).get("receive_port", 8000))

    # Inject resolved values into config
    config["network"]["ip_address"] = ip_address

    # Override listen address for test environments (e.g. 192.168.3.x)
    if opt.listen_host:
        config["network"]["ip_address"] = opt.listen_host
        logger.info(f"Overriding listen address: {opt.listen_host}")
    config["targets"] = targets
    config.setdefault("audio", {})["device_id"] = device_id  # for per-node voice character

    # Auto-detect language from device ID
    lang = resolve_lang_from_device_id(device_id)
    config.setdefault("common", {})["lang"] = lang
    logger.info(f"Language: {lang} (device_id={device_id}, last_digit={device_id % 10})")

    logger.info(f"Device IP: {ip_address}")
    logger.info(f"Targets: {targets}")

    # Start LED server (daemon threads, must be before BI controller)
    start_led_server(config)

    # Initialize controllers
    logger.info("Starting BI system")
    app = AppController(config)
    bi = BIController(config)

    # Register BI-specific handlers
    def handle_bi_input(_, *args):
        # OSC message format: /bi/input text soft_prefix_b64 relay_count
        bi.add_input(text=args[0], soft_prefix_b64=args[1], relay_count=args[2])

    def handle_bi_stop(_, *__):
        bi.stop_cycle()

    def handle_bi_status(_, *__):
        logger.info(f"BI Status: {bi.get_status()}")

    def handle_soft_prefix_update(_, *args):
        """Handle soft prefix update event with LED performance.

        OSC message format: /bi/soft_prefix_update fade_up_duration fade_down_duration

        Args:
            args[0]: fade_up_duration (float) - Duration in seconds for fade up (0.0 -> 1.0)
            args[1]: fade_down_duration (float) - Duration in seconds for fade down (1.0 -> 0.0)
        """
        if len(args) < 2:
            logger.warning(f"Invalid args for /bi/soft_prefix_update: {args}")
            return

        try:
            fade_up = float(args[0])
            fade_down = float(args[1])

            # Start LED performance task (non-blocking)
            asyncio.create_task(bi.start_soft_prefix_led_performance(fade_up, fade_down))

            logger.info(f"Soft prefix update: LED performance triggered (up={fade_up}s, down={fade_down}s)")
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to parse soft_prefix_update args: {args}, error: {e}")

    def handle_bri_ex(_, *args):
        """Handle /bi/bri_ex <float 0.0..1.0>"""
        if len(args) < 1:
            return
        try:
            value = float(args[0])
            asyncio.create_task(bi.set_bri_ex(value))
            logger.debug(f"bri_ex set to {value}")
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to parse bri_ex args: {args}, error: {e}")

    def handle_led_ratio(_, *args):
        """Handle /bi/led_ratio <float 0.0..1.0>"""
        if len(args) < 1:
            return
        try:
            value = float(args[0])
            asyncio.create_task(bi.set_led_ratio(value))
            logger.debug(f"led_ratio set to {value}")
        except (ValueError, TypeError) as e:
            logger.error(f"Failed to parse led_ratio args: {args}, error: {e}")

    app.osc_server.register_handler("/bi/input", handle_bi_input)
    app.osc_server.register_handler("/bi/stop", handle_bi_stop)
    app.osc_server.register_handler("/bi/status", handle_bi_status)
    app.osc_server.register_handler("/bi/soft_prefix_update", handle_soft_prefix_update)
    app.osc_server.register_handler("/bi/bri_ex", handle_bri_ex)
    app.osc_server.register_handler("/bi/led_ratio", handle_led_ratio)

    # Auto-start BI cycle on startup
    logger.info("Auto-starting BI cycle")
    asyncio.create_task(bi.start_cycle())

    # Run app
    await app.run()


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
