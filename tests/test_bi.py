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

    # Start BI cycle
    print("\n1. Starting BI cycle...")
    client.send_message("/bi/start", [])
    time.sleep(0.5)

    # Send first human input
    print("\n2. Sending first human input: 'こんにちは'")
    timestamp1 = time.time()
    client.send_message("/bi/input", [timestamp1, "こんにちは", "human", "ja"])
    time.sleep(1.0)

    # Send second human input
    print("\n3. Sending second human input: '世界'")
    timestamp2 = time.time()
    client.send_message("/bi/input", [timestamp2, "世界", "human", "ja"])
    time.sleep(0.5)

    # Simulate BI input
    print("\n4. Sending BI input: 'よ'")
    timestamp3 = time.time()
    client.send_message("/bi/input", [timestamp3, "よ", "BI", "ja"])
    time.sleep(0.5)

    # Check status
    print("\n5. Checking status...")
    client.send_message("/bi/status", [])
    time.sleep(1.0)

    # Wait for the cycle to complete
    print("\n6. Waiting for cycle to complete...")
    time.sleep(5.0)

    # Send another round of inputs
    print("\n7. Sending new inputs for second cycle...")
    timestamp4 = time.time()
    client.send_message("/bi/input", [timestamp4, "静かな", "human", "ja"])
    time.sleep(1.0)

    timestamp5 = time.time()
    client.send_message("/bi/input", [timestamp5, "夜", "human", "ja"])
    time.sleep(3.0)

    # Check status again
    print("\n8. Checking status again...")
    client.send_message("/bi/status", [])
    time.sleep(1.0)

    # Wait for the second cycle
    print("\n9. Waiting for second cycle to complete...")
    time.sleep(5.0)

    # Stop cycle
    print("\n10. Stopping BI cycle...")
    client.send_message("/bi/stop", [])

    print("\n" + "=" * 50)
    print("Test completed!")


def test_old_data_filtering(host: str = "192.168.151.31", port: int = 8000):
    """Test old data filtering (61+ seconds old)"""
    client = udp_client.SimpleUDPClient(host, port)

    print(f"Testing old data filtering at {host}:{port}")
    print("=" * 50)

    # Start cycle
    print("\n1. Starting BI cycle...")
    client.send_message("/bi/start", [])
    time.sleep(0.5)

    # Send very old data (should be filtered out)
    print("\n2. Sending old data (61 seconds ago)...")
    old_timestamp = time.time() - 61.0
    client.send_message("/bi/input", [old_timestamp, "古いデータ", "human", "ja"])
    time.sleep(0.5)

    # Send recent data (should be kept)
    print("\n3. Sending recent data...")
    recent_timestamp = time.time()
    client.send_message("/bi/input", [recent_timestamp, "新しいデータ", "human", "ja"])
    time.sleep(3.0)

    # Check status
    print("\n4. Checking status (should only have 1 item)...")
    client.send_message("/bi/status", [])
    time.sleep(1.0)

    # Wait for cycle
    print("\n5. Waiting for cycle to complete...")
    time.sleep(5.0)

    # Stop
    print("\n6. Stopping BI cycle...")
    client.send_message("/bi/stop", [])

    print("\n" + "=" * 50)
    print("Old data filtering test completed!")


def test_2nd_bi_mode(host: str = "192.168.151.31", port: int = 8000):
    """
    Test 2nd_BI mode (should ignore human inputs)
    Note: Change config device.type to "2nd_BI" before running this test
    """
    client = udp_client.SimpleUDPClient(host, port)

    print(f"Testing 2nd_BI mode at {host}:{port}")
    print("=" * 50)
    print("NOTE: Ensure device.type is set to '2nd_BI' in config")

    # Start cycle
    print("\n1. Starting BI cycle...")
    client.send_message("/bi/start", [])
    time.sleep(0.5)

    # Send human input (should be ignored)
    print("\n2. Sending human input (should be ignored)...")
    timestamp1 = time.time()
    client.send_message("/bi/input", [timestamp1, "人間の入力", "human", "ja"])
    time.sleep(1.0)

    # Send BI input (should be accepted)
    print("\n3. Sending BI input (should be accepted)...")
    timestamp2 = time.time()
    client.send_message("/bi/input", [timestamp2, "BIからの入力", "BI", "ja"])
    time.sleep(3.0)

    # Check status
    print("\n4. Checking status (should only have BI input)...")
    client.send_message("/bi/status", [])
    time.sleep(1.0)

    # Wait for cycle
    print("\n5. Waiting for cycle to complete...")
    time.sleep(5.0)

    # Stop
    print("\n6. Stopping BI cycle...")
    client.send_message("/bi/stop", [])

    print("\n" + "=" * 50)
    print("2nd_BI mode test completed!")


def main():
    parser = argparse.ArgumentParser(description="Test script for BI system")
    parser.add_argument("--host", type=str, default="192.168.151.31", help="Target host IP address")
    parser.add_argument("--port", type=int, default=8000, help="Target port")
    parser.add_argument(
        "--test", type=str, default="cycle", choices=["cycle", "filter", "2nd_bi", "all"], help="Test to run"
    )

    args = parser.parse_args()

    if args.test == "cycle":
        test_bi_cycle(args.host, args.port)
    elif args.test == "filter":
        test_old_data_filtering(args.host, args.port)
    elif args.test == "2nd_bi":
        test_2nd_bi_mode(args.host, args.port)
    elif args.test == "all":
        test_bi_cycle(args.host, args.port)
        time.sleep(2)
        test_old_data_filtering(args.host, args.port)
        print("\n\nFor 2nd_BI test, change config and run:")
        print(f"  python test_bi.py --host {args.host} --test 2nd_bi")


if __name__ == "__main__":
    main()
