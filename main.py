import argparse
import asyncio
import json

from loguru import logger

from app import AppController
from bi import BIController
from pca9685_osc_led_server import start_led_server
from utils import load_network_config


DEVICE_ID_FILE = "/etc/ccbt-device-id"
NETWORK_INTERFACES = "/etc/network/interfaces"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_path", type=str, default="config/config.json")
    parser.add_argument("--device-id", type=int, default=None,
                        help="Device ID (e.g. 61). If omitted, auto-detected from network config")
    parser.add_argument("--raw-audio", action="store_true",
                        help="Debug mode: skip FFmpeg processing, save raw WAV, play with aplay")
    return parser.parse_args()


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
    config["targets"] = targets

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

    app.osc_server.register_handler("/bi/input", handle_bi_input)
    app.osc_server.register_handler("/bi/stop", handle_bi_stop)
    app.osc_server.register_handler("/bi/status", handle_bi_status)

    # Auto-start BI cycle on startup
    logger.info("Auto-starting BI cycle")
    asyncio.create_task(bi.start_cycle())

    # Run app
    await app.run()


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
