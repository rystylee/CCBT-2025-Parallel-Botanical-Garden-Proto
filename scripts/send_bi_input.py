#!/usr/bin/env python3
"""
Debug script to send /bi/input OSC messages to a running BI device.

Usage:
    python scripts/send_bi_input.py --host 192.168.1.100 --text "こんにちは"
    python scripts/send_bi_input.py -H 192.168.1.100 -t "Hello world" -s BI -l en
"""

import argparse
import time

from pythonosc import udp_client


def send_bi_input(
    host: str,
    port: int,
    text: str,
    source_type: str = "human",
    lang: str = "ja",
    timestamp: float | None = None,
):
    """Send /bi/input OSC message to target device."""
    if timestamp is None:
        timestamp = time.time()

    client = udp_client.SimpleUDPClient(host, port)

    print(f"Sending to {host}:{port}")
    print(f"  Address: /bi/input")
    print(f"  Timestamp: {timestamp}")
    print(f"  Text: {text}")
    print(f"  Source Type: {source_type}")
    print(f"  Language: {lang}")

    client.send_message("/bi/input", [timestamp, text, source_type, lang])
    print("✓ Message sent successfully")


def main():
    parser = argparse.ArgumentParser(
        description="Send /bi/input OSC message for debugging",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Send human input (Japanese)
  python scripts/send_bi_input.py -H 192.168.1.100 -t "こんにちは"

  # Send BI input (English)
  python scripts/send_bi_input.py -H 192.168.1.100 -t "Hello" -s BI -l en

  # Send to custom port
  python scripts/send_bi_input.py -H 192.168.1.100 -p 9000 -t "世界"

  # Send with custom timestamp
  python scripts/send_bi_input.py -H 192.168.1.100 -t "test" --timestamp 1234567890.5
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
        "-s",
        "--source-type",
        type=str,
        choices=["human", "BI"],
        default="human",
        help="Source type: 'human' or 'BI' (default: human)",
    )

    parser.add_argument(
        "-l",
        "--lang",
        type=str,
        choices=["ja", "en", "zh", "fr"],
        default="ja",
        help="Language code (default: ja)",
    )

    parser.add_argument(
        "--timestamp",
        type=float,
        default=None,
        help="Custom timestamp (default: current time)",
    )

    args = parser.parse_args()

    try:
        send_bi_input(
            host=args.host,
            port=args.port,
            text=args.text,
            source_type=args.source_type,
            lang=args.lang,
            timestamp=args.timestamp,
        )
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
