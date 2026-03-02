#!/usr/bin/env python3
"""
Test script for multiple OSC target sending
"""
import base64
import json
import random
import struct

from loguru import logger

from api.osc import OscClient

# Soft prefix generation utilities (copied from bi/utils.py)
P = 1  # num prefix_token
H = 1536  # tokens_embed_size
VALS = [0.0, 1e-4, 1e-3, 1e-2, 5e-2, 1e-1, 2e-1, 5e-1, 1.0, 2.0]


def f32_to_bf16_u16(x: float) -> int:
    """float32 -> bf16 (truncate) -> u16"""
    u32 = struct.unpack("<I", struct.pack("<f", x))[0]
    return (u32 >> 16) & 0xFFFF


def make_soft_prefix_b64_constant(P: int, H: int, val: float) -> str:
    """arrange bf16 little-endian u16 in P*H groups to create base64"""
    u16 = f32_to_bf16_u16(val)
    raw = struct.pack("<H", u16) * (P * H)
    return base64.b64encode(raw).decode("ascii")


def make_random_soft_prefix_b64() -> str:
    """Generate random soft prefix for testing"""
    v = random.choice(VALS)
    return make_soft_prefix_b64_constant(P, H, v)


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
    relay_count = 1
    test_text = "テストメッセージ"
    soft_prefix_b64 = make_random_soft_prefix_b64()

    logger.info("Sending to all targets...")
    osc_client.send_to_all_targets(config["targets"], "/bi/input", test_text, soft_prefix_b64, relay_count)

    logger.info("Multi-target send test completed!")


if __name__ == "__main__":
    test_multi_target_send()
