#!/usr/bin/env python3
"""
Debug script to send /bi/input OSC messages to a running BI device.

Usage:
    python scripts/send_bi_input.py --host 192.168.1.100 --text "こんにちは"
    python scripts/send_bi_input.py -H 192.168.1.100 -t "Hello world" -r 2
    python scripts/send_bi_input.py -H 192.168.1.100 -t "Hello" -s <base64_soft_prefix>
"""

import argparse
import base64
import random
import struct

from pythonosc import udp_client

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


def send_bi_input(
    host: str,
    port: int,
    text: str,
    soft_prefix_b64: str | None = None,
    relay_count: int = 0,
):
    """Send /bi/input OSC message to target device."""
    client = udp_client.SimpleUDPClient(host, port)

    # Generate random soft prefix if not provided
    if soft_prefix_b64 is None:
        soft_prefix_b64 = make_random_soft_prefix_b64()

    print(f"Sending to {host}:{port}")
    print("  Address: /bi/input")
    print(f"  Text: {text}")
    print(f"  Soft Prefix (b64): {soft_prefix_b64[:30]}...")
    print(f"  Relay Count: {relay_count}")

    client.send_message("/bi/input", [text, soft_prefix_b64, relay_count])
    print("✓ Message sent successfully")


def main():
    parser = argparse.ArgumentParser(
        description="Send /bi/input OSC message for debugging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Send input with relay_count 0 (default, random soft prefix)
  python scripts/send_bi_input.py -H 192.168.1.100 -t "こんにちは"

  # Send input with relay_count 2
  python scripts/send_bi_input.py -H 192.168.1.100 -t "Hello" -r 2

  # Send with custom soft prefix
  python scripts/send_bi_input.py -H 192.168.1.100 -t "World" -s "<base64_string>"

  # Send to custom port
  python scripts/send_bi_input.py -H 192.168.1.100 -p 9000 -t "世界"
        """,
    )

    parser.add_argument(
        "-H",
        "--host",
        type=str,
        required=True,
        help="Target host IP address (e.g., 192.168.1.100)",
    )

    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=8000,
        help="Target OSC port (default: 8000)",
    )

    parser.add_argument(
        "-t",
        "--text",
        type=str,
        required=True,
        help="Text content to send",
    )

    parser.add_argument(
        "-r",
        "--relay-count",
        type=int,
        default=0,
        help="Relay count (default: 0)",
    )

    parser.add_argument(
        "-s",
        "--soft-prefix",
        type=str,
        default=None,
        help="Base64-encoded soft prefix (if not provided, random one will be generated)",
    )

    args = parser.parse_args()

    try:
        send_bi_input(
            host=args.host,
            port=args.port,
            text=args.text,
            soft_prefix_b64=args.soft_prefix,
            relay_count=args.relay_count,
        )
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
