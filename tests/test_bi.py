#!/usr/bin/env python3
"""
Test script for Botanical Intelligence (BI) system
"""
import argparse
import time

from pythonosc import udp_client


def test_bi_cycle(host: str = "192.168.151.31", port: int = 8000):
    """Test BI cycle with multiple inputs"""
    client = udp_client.SimpleUDPClient(host, port)

    print(f"Testing BI system at {host}:{port}")
    print("=" * 50)
    print("NOTE: BI cycle starts automatically on application startup")

    # Send first input
    print("\n1. Sending first input: 'こんにちは' (relay_count=0)")
    client.send_message("/bi/input", [0, "こんにちは"])
    time.sleep(1.0)

    # Send second input
    print("\n2. Sending second input: '世界' (relay_count=0)")
    client.send_message("/bi/input", [0, "世界"])
    time.sleep(0.5)

    # Send third input
    print("\n3. Sending third input: 'よ' (relay_count=1)")
    client.send_message("/bi/input", [1, "よ"])
    time.sleep(0.5)

    # Check status
    print("\n4. Checking status...")
    client.send_message("/bi/status", [])
    time.sleep(1.0)

    # Wait for the cycle to complete
    print("\n5. Waiting for cycle to complete...")
    time.sleep(5.0)

    # Send another round of inputs
    print("\n6. Sending new inputs for second cycle...")
    client.send_message("/bi/input", [0, "静かな"])
    time.sleep(1.0)

    client.send_message("/bi/input", [0, "夜"])
    time.sleep(3.0)

    # Check status again
    print("\n7. Checking status again...")
    client.send_message("/bi/status", [])
    time.sleep(1.0)

    # Wait for the second cycle
    print("\n8. Waiting for second cycle to complete...")
    time.sleep(5.0)

    # Stop cycle
    print("\n9. Stopping BI cycle...")
    client.send_message("/bi/stop", [])

    print("\n" + "=" * 50)
    print("Test completed!")


def test_relay_count_filtering(host: str = "192.168.151.31", port: int = 8000):
    """Test relay count filtering (max_relay_count=6)"""
    client = udp_client.SimpleUDPClient(host, port)

    print(f"Testing relay count filtering at {host}:{port}")
    print("=" * 50)
    print("NOTE: BI cycle starts automatically on application startup")

    # Send data with high relay count (should be filtered out)
    print("\n1. Sending data with relay_count=6 (should be rejected)...")
    client.send_message("/bi/input", [6, "リレー回数が多すぎるデータ"])
    time.sleep(0.5)

    # Send data with normal relay count (should be kept)
    print("\n2. Sending data with relay_count=0 (should be accepted)...")
    client.send_message("/bi/input", [0, "正常なデータ"])
    time.sleep(3.0)

    # Check status
    print("\n3. Checking status (should only have 1 item)...")
    client.send_message("/bi/status", [])
    time.sleep(1.0)

    # Wait for cycle
    print("\n4. Waiting for cycle to complete...")
    time.sleep(5.0)

    # Stop
    print("\n5. Stopping BI cycle...")
    client.send_message("/bi/stop", [])

    print("\n" + "=" * 50)
    print("Relay count filtering test completed!")


def test_mixed_relay_counts(host: str = "192.168.151.31", port: int = 8000):
    """
    Test mixed relay counts
    """
    client = udp_client.SimpleUDPClient(host, port)

    print(f"Testing mixed relay counts at {host}:{port}")
    print("=" * 50)
    print("NOTE: BI cycle starts automatically on application startup")

    # Send input with relay_count=0
    print("\n1. Sending input with relay_count=0...")
    client.send_message("/bi/input", [0, "初期入力"])
    time.sleep(1.0)

    # Send input with relay_count=3
    print("\n2. Sending input with relay_count=3...")
    client.send_message("/bi/input", [3, "リレーされた入力"])
    time.sleep(3.0)

    # Check status
    print("\n3. Checking status (should have both inputs)...")
    client.send_message("/bi/status", [])
    time.sleep(1.0)

    # Wait for cycle
    print("\n4. Waiting for cycle to complete...")
    time.sleep(5.0)

    # Stop
    print("\n5. Stopping BI cycle...")
    client.send_message("/bi/stop", [])

    print("\n" + "=" * 50)
    print("Mixed relay counts test completed!")


def main():
    parser = argparse.ArgumentParser(description="Test script for BI system")
    parser.add_argument("--host", type=str, default="192.168.151.31", help="Target host IP address")
    parser.add_argument("--port", type=int, default=8000, help="Target port")
    parser.add_argument(
        "--test", type=str, default="cycle", choices=["cycle", "filter", "mixed", "all"], help="Test to run"
    )

    args = parser.parse_args()

    if args.test == "cycle":
        test_bi_cycle(args.host, args.port)
    elif args.test == "filter":
        test_relay_count_filtering(args.host, args.port)
    elif args.test == "mixed":
        test_mixed_relay_counts(args.host, args.port)
    elif args.test == "all":
        test_bi_cycle(args.host, args.port)
        time.sleep(2)
        test_relay_count_filtering(args.host, args.port)
        time.sleep(2)
        test_mixed_relay_counts(args.host, args.port)


if __name__ == "__main__":
    main()
