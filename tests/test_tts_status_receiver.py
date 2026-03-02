#!/usr/bin/env python3
"""
Test script to receive TTS status notifications via OSC.

This script listens for /bi/tts/start and /bi/tts/end messages
and prints them to the console for debugging purposes.

Usage:
    python tests/test_tts_status_receiver.py [--port PORT]
"""

import argparse
import asyncio
from datetime import datetime

from loguru import logger
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer


def handle_tts_start(address: str, *args):
    """
    Handle /bi/tts/start message.

    Expected args:
        device_id (int): BI device ID
        text (str): TTS text being spoken
        timestamp (float): Unix timestamp when TTS started
    """
    if len(args) >= 3:
        device_id, text, timestamp = args[0], args[1], args[2]
        dt = datetime.fromtimestamp(timestamp)
        logger.info(f"[TTS START] Device {device_id} | Time: {dt.strftime('%H:%M:%S.%f')[:-3]}")
        logger.info(f"            Text: {text[:100]}...")
    else:
        logger.warning(f"[TTS START] Invalid args: {args}")


def handle_tts_end(address: str, *args):
    """
    Handle /bi/tts/end message.

    Expected args:
        device_id (int): BI device ID
        timestamp (float): Unix timestamp when TTS ended
        error (int): 0 if success, 1 if error
    """
    if len(args) >= 3:
        device_id, timestamp, error = args[0], args[1], args[2]
        dt = datetime.fromtimestamp(timestamp)
        status = "ERROR" if error else "SUCCESS"
        logger.info(f"[TTS END]   Device {device_id} | Time: {dt.strftime('%H:%M:%S.%f')[:-3]} | Status: {status}")
    else:
        logger.warning(f"[TTS END] Invalid args: {args}")


def handle_tts_simple(address: str, *args):
    """
    Handle /bi/tts message (simple status).

    Expected args:
        device_id (int): BI device ID
        status (int): 1 if speaking, 0 if not speaking
    """
    if len(args) >= 2:
        device_id, status = args[0], args[1]
        status_str = "SPEAKING" if status == 1 else "SILENT"
        logger.info(f"[TTS SIMPLE] Device {device_id} | Status: {status_str} ({status})")
    else:
        logger.warning(f"[TTS SIMPLE] Invalid args: {args}")


def handle_default(address: str, *args):
    """Handle any other OSC message"""
    logger.debug(f"[OSC] {address}: {args}")


async def main():
    parser = argparse.ArgumentParser(description="TTS Status Notification Receiver (for testing)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="OSC server host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=9000, help="OSC server port (default: 9000)")
    args = parser.parse_args()

    # Setup OSC dispatcher
    dispatcher = Dispatcher()
    dispatcher.map("/bi/tts/start", handle_tts_start)
    dispatcher.map("/bi/tts/end", handle_tts_end)
    dispatcher.map("/bi/tts", handle_tts_simple)
    dispatcher.set_default_handler(handle_default)

    # Create and start OSC server
    server = AsyncIOOSCUDPServer((args.host, args.port), dispatcher, asyncio.get_event_loop())
    transport, protocol = await server.create_serve_endpoint()

    logger.info(f"TTS Status Receiver listening on {args.host}:{args.port}")
    logger.info("Waiting for TTS status notifications...")
    logger.info("Press Ctrl+C to stop")

    try:
        await asyncio.Event().wait()  # Run forever
    except KeyboardInterrupt:
        logger.info("Stopping server...")
    finally:
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
