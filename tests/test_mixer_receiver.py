#!/usr/bin/env python3
"""
Test script to receive OSC messages from BI devices as a Mixer PC.
This script listens on /mixer endpoint and prints received messages.

Usage:
    python tests/test_mixer_receiver.py [--host HOST] [--port PORT]
"""

import argparse
import asyncio

from loguru import logger
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer


def handle_mixer_message(address: str, *args):
    """Handle /mixer OSC message"""
    logger.info(f"Received on {address}: {args}")
    if args:
        logger.success(f"Generated text from BI: '{args[0]}'")


async def run_receiver(host: str, port: int):
    """Run OSC receiver for Mixer PC"""
    dispatcher = Dispatcher()
    dispatcher.map("/mixer", handle_mixer_message)
    dispatcher.map("/*", lambda addr, *args: logger.debug(f"Other message: {addr} {args}"))

    server = AsyncIOOSCUDPServer((host, port), dispatcher, asyncio.get_event_loop())
    transport, protocol = await server.create_serve_endpoint()

    logger.info(f"Mixer PC receiver listening on {host}:{port}")
    logger.info("Waiting for /mixer messages from BI devices...")

    try:
        await asyncio.Future()  # Run forever
    finally:
        transport.close()


def main():
    parser = argparse.ArgumentParser(description="Mixer PC OSC receiver for testing")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Listen IP address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Listen port (default: 8000)")
    args = parser.parse_args()

    logger.info(f"Starting Mixer PC receiver on {args.host}:{args.port}")
    asyncio.run(run_receiver(args.host, args.port))


if __name__ == "__main__":
    main()
