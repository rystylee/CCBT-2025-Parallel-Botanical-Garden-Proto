#!/usr/bin/env python3
"""
Debug script to send /bi/input OSC messages to a running BI device.

Usage:
    python scripts/send_bi_input.py --host 192.168.1.100 --text "こんにちは"
    python scripts/send_bi_input.py -H 192.168.1.100 -t "Hello world" -r 2
"""

import argparse

from pythonosc import udp_client


def send_bi_input(
    host: str,
    port: int,
    text: str,
    relay_count: int = 0,
):
    """Send /bi/input OSC message to target device."""
    client = udp_client.SimpleUDPClient(host, port)

    print(f"Sending to {host}:{port}")
    print("  Address: /bi/input")
    print(f"  Relay Count: {relay_count}")
    print(f"  Text: {text}")

    client.send_message("/bi/input", [relay_count, text])
    print("✓ Message sent successfully")


def main():
    parser = argparse.ArgumentParser(
        description="Send /bi/input OSC message for debugging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Send input with relay_count 0 (default)
  python scripts/send_bi_input.py -H 192.168.1.100 -t "こんにちは"

  # Send input with relay_count 2
  python scripts/send_bi_input.py -H 192.168.1.100 -t "Hello" -r 2

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

    args = parser.parse_args()

    try:
        send_bi_input(
            host=args.host,
            port=args.port,
            text=args.text,
            relay_count=args.relay_count,
        )
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
