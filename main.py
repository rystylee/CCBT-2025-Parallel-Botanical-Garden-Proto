import argparse
import asyncio
import json
from loguru import logger

from app import AppController


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config_path", type=str, default="config/config.json")
    return parser.parse_args()


def main():
    opt = parse_args()

    with open(opt.config_path, mode="r", encoding="utf-8") as f:
        config = json.load(f)

    app = AppController(config)
    asyncio.run(app.run())


if __name__ == "__main__":
    main()
