import argparse
import asyncio
import json

from loguru import logger

from app import AppController, BIController


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_path", type=str, default="config/config.json")
    return parser.parse_args()


def main():
    opt = parse_args()

    with open(opt.config_path, mode="r", encoding="utf-8") as f:
        config = json.load(f)

    # Initialize controllers
    logger.info("Starting BI system")
    app = AppController(config)
    bi = BIController(config)

    # Register BI-specific handlers
    def handle_bi_input(_, *args):
        bi.add_input(args[0], args[1], args[2], args[3])

    def handle_bi_start(_, *__):
        asyncio.create_task(bi.start_cycle())

    def handle_bi_stop(_, *__):
        bi.stop_cycle()

    def handle_bi_status(_, *__):
        logger.info(f"BI Status: {bi.get_status()}")

    app.osc_server.register_handler("/bi/input", handle_bi_input)
    app.osc_server.register_handler("/bi/start", handle_bi_start)
    app.osc_server.register_handler("/bi/stop", handle_bi_stop)
    app.osc_server.register_handler("/bi/status", handle_bi_status)

    # Run app
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
