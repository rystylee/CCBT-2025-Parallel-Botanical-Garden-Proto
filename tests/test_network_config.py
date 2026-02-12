"""Test script for network configuration CSV loader"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from utils import load_network_config


def test_load_csv():
    """Test loading networks.csv"""
    logger.info("=" * 50)
    logger.info("Test: Load networks.csv")
    logger.info("=" * 50)

    csv_path = "config/networks.csv"
    network_config = load_network_config(csv_path)

    logger.info(f"Total devices loaded: {len(network_config.devices)}")
    logger.info("")


def test_device_info():
    """Test getting device information"""
    logger.info("=" * 50)
    logger.info("Test: Get device information")
    logger.info("=" * 50)

    network_config = load_network_config("config/networks.csv")

    # Test device with IP
    device_id = 1
    device_info = network_config.get_device_info(device_id)
    logger.info(f"Device {device_id}: {device_info}")

    # Test device without IP
    device_id = 11
    device_info = network_config.get_device_info(device_id)
    logger.info(f"Device {device_id}: {device_info}")

    # Test non-existent device
    device_id = 999
    device_info = network_config.get_device_info(device_id)
    logger.info(f"Device {device_id}: {device_info}")
    logger.info("")


def test_resolve_targets():
    """Test resolving target devices"""
    logger.info("=" * 50)
    logger.info("Test: Resolve targets")
    logger.info("=" * 50)

    network_config = load_network_config("config/networks.csv")

    # Test device 1 (IP: 10.0.0.1, To: "2,5")
    device_id = 1
    targets = network_config.resolve_targets(device_id, port=8000)
    logger.info(f"Device {device_id} targets: {targets}")

    # Test device 6 (IP: 10.0.0.6, To: "7,10,11")
    # Note: Device 11 has no IP, so should be skipped
    device_id = 6
    targets = network_config.resolve_targets(device_id, port=8000)
    logger.info(f"Device {device_id} targets: {targets}")

    # Test device with no targets
    device_id = 51
    targets = network_config.resolve_targets(device_id, port=8000)
    logger.info(f"Device {device_id} targets: {targets}")
    logger.info("")


def test_config_integration():
    """Test integration with config.json"""
    logger.info("=" * 50)
    logger.info("Test: Config integration")
    logger.info("=" * 50)

    import json

    with open("config/config.json", "r") as f:
        config = json.load(f)

    device_id = config.get("network", {}).get("device_id")
    csv_path = config.get("network", {}).get("csv_path", "networks.csv")

    logger.info(f"Config device_id: {device_id}")
    logger.info(f"Config csv_path: {csv_path}")

    network_config = load_network_config(csv_path)

    ip_address = network_config.get_ip_address(device_id)
    targets = network_config.resolve_targets(device_id, port=config.get("osc", {}).get("receive_port", 8000))

    logger.info(f"Resolved IP: {ip_address}")
    logger.info(f"Resolved targets: {targets}")
    logger.info("")


if __name__ == "__main__":
    logger.info("Starting network configuration tests\n")

    try:
        test_load_csv()
        test_device_info()
        test_resolve_targets()
        test_config_integration()
        logger.success("All tests completed!")
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
