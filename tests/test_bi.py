#!/usr/bin/env python3
"""
Test script for Botanical Intelligence (BI) system
"""
import argparse
import base64
import random
import struct
import time

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


def test_bi_cycle(host: str = "192.168.151.31", port: int = 8000):
    """Test BI cycle with multiple inputs"""
    client = udp_client.SimpleUDPClient(host, port)

    print(f"Testing BI system at {host}:{port}")
    print("=" * 50)
    print("NOTE: BI cycle starts automatically on application startup")

    # Send first input
    print("\n1. Sending first input: 'こんにちは' (relay_count=0)")
    sp1 = make_random_soft_prefix_b64()
    client.send_message("/bi/input", ["こんにちは", sp1, 0])
    time.sleep(1.0)

    # Send second input
    print("\n2. Sending second input: '世界' (relay_count=0)")
    sp2 = make_random_soft_prefix_b64()
    client.send_message("/bi/input", ["世界", sp2, 0])
    time.sleep(0.5)

    # Send third input
    print("\n3. Sending third input: 'よ' (relay_count=1)")
    sp3 = make_random_soft_prefix_b64()
    client.send_message("/bi/input", ["よ", sp3, 1])
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
    sp4 = make_random_soft_prefix_b64()
    client.send_message("/bi/input", ["静かな", sp4, 0])
    time.sleep(1.0)

    sp5 = make_random_soft_prefix_b64()
    client.send_message("/bi/input", ["夜", sp5, 0])
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
    sp1 = make_random_soft_prefix_b64()
    client.send_message("/bi/input", ["リレー回数が多すぎるデータ", sp1, 6])
    time.sleep(0.5)

    # Send data with normal relay count (should be kept)
    print("\n2. Sending data with relay_count=0 (should be accepted)...")
    sp2 = make_random_soft_prefix_b64()
    client.send_message("/bi/input", ["正常なデータ", sp2, 0])
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
    sp1 = make_random_soft_prefix_b64()
    client.send_message("/bi/input", ["初期入力", sp1, 0])
    time.sleep(1.0)

    # Send input with relay_count=3
    print("\n2. Sending input with relay_count=3...")
    sp2 = make_random_soft_prefix_b64()
    client.send_message("/bi/input", ["リレーされた入力", sp2, 3])
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
