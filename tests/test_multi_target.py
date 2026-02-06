#!/usr/bin/env python3
"""
Test script for multiple OSC target sending
"""
import json

from loguru import logger

from api.osc import OscClient


def test_multi_target_send():
    """Test sending OSC messages to multiple targets"""

    # Load config
    with open("config/config.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    # Add additional test targets
    config["targets"] = [
        {"host": "192.168.151.32", "port": 8000},
        {"host": "192.168.151.33", "port": 8000},
        {"host": "192.168.151.34", "port": 8000},
    ]

    logger.info(f"Testing multi-target send with {len(config['targets'])} targets")

    # Initialize OSC client
    osc_client = OscClient(config)

    # Test send to all targets
    import time

    timestamp = time.time()
    test_text = "テストメッセージ"

    logger.info("Sending to all targets...")
    osc_client.send_to_all_targets(config["targets"], "/bi/input", timestamp, test_text, "BI", "ja")

    logger.info("Multi-target send test completed!")


if __name__ == "__main__":
    test_multi_target_send()
