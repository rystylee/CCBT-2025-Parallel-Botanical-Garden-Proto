import argparse
import random

from loguru import logger
from pythonosc import udp_client


def get_random_input():
    return random.choice([
        "生命",
        "この世界は",
        "宇宙"
    ]) 


def send_message(ip, port, address, message):
    client = udp_client.SimpleUDPClient(ip, port)
    client.send_message(address, message)
    logger.info(f"Sent to {address}: {message}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--address", default="/process")
    parser.add_argument("--message", default="")
    args = parser.parse_args()
    
    message = args.message if args.message else get_random_input()
    send_message(args.ip, args.port, args.address, message)
