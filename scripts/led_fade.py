#!/usr/bin/env python3
"""
LED fade script to send /led OSC messages with gradual brightness changes.

Usage:
    python scripts/led_fade.py --host 10.0.0.59 --port 9000
    python scripts/led_fade.py -H 10.0.0.59 -p 9000 --steps 40 --up 2 --down 2
"""

import argparse
import time

from pythonosc import udp_client


def fade_led(
    host: str,
    port: int,
    steps: int = 40,
    up_duration: float = 2.0,
    down_duration: float = 2.0,
):
    """
    Send /led OSC messages to gradually fade LED brightness up and down.

    Args:
        host: Target host IP address
        port: Target OSC port
        steps: Number of steps for the fade (default: 40)
        up_duration: Duration in seconds for fade up (default: 2.0)
        down_duration: Duration in seconds for fade down (default: 2.0)
    """
    client = udp_client.SimpleUDPClient(host, port)

    # Calculate delay between steps
    dt_up = up_duration / steps
    dt_down = down_duration / steps

    print(f"Sending to {host}:{port}")
    print(f"Steps: {steps}, Up: {up_duration}s, Down: {down_duration}s")
    print(f"Step delay: up={dt_up:.4f}s, down={dt_down:.4f}s")
    print()

    # Fade up: 0 -> 1
    print("Fading up...")
    for i in range(steps + 1):
        value = i / steps
        client.send_message("/led", [value])
        print(f"  Step {i}/{steps}: {value:.4f}")
        if i < steps:  # Don't sleep after the last step
            time.sleep(dt_up)

    # Fade down: 1 -> 0
    print("\nFading down...")
    for i in range(steps, -1, -1):
        value = i / steps
        client.send_message("/led", [value])
        print(f"  Step {steps - i}/{steps}: {value:.4f}")
        if i > 0:  # Don't sleep after the last step
            time.sleep(dt_down)

    print("\n✓ Fade complete")


def main():
    parser = argparse.ArgumentParser(
        description="Send /led OSC messages with gradual fade up and down",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic fade with default settings
  python scripts/led_fade.py -H 10.0.0.59 -p 9000

  # Custom fade with 20 steps, 1 second up, 3 seconds down
  python scripts/led_fade.py -H 10.0.0.59 -p 9000 --steps 20 --up 1 --down 3

  # Fast fade
  python scripts/led_fade.py -H 10.0.0.59 -p 9000 --steps 10 --up 0.5 --down 0.5
        """,
    )

    parser.add_argument(
        "-H",
        "--host",
        type=str,
        required=True,
        help="Target host IP address (e.g., 10.0.0.59)",
    )

    parser.add_argument(
        "-p",
        "--port",
        type=int,
        required=True,
        help="Target OSC port (e.g., 9000)",
    )

    parser.add_argument(
        "--steps",
        type=int,
        default=40,
        help="Number of fade steps (default: 40)",
    )

    parser.add_argument(
        "--up",
        type=float,
        default=2.0,
        help="Fade up duration in seconds (default: 2.0)",
    )

    parser.add_argument(
        "--down",
        type=float,
        default=2.0,
        help="Fade down duration in seconds (default: 2.0)",
    )

    args = parser.parse_args()

    try:
        fade_led(
            host=args.host,
            port=args.port,
            steps=args.steps,
            up_duration=args.up,
            down_duration=args.down,
        )
    except Exception as e:
        print(f"✗ Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
