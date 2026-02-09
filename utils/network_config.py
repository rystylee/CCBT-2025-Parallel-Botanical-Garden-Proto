"""Network configuration loader from CSV file"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from loguru import logger


@dataclass
class DeviceInfo:
    """Device information from networks.csv"""

    device_id: int
    ip_address: Optional[str]
    target_ids: List[int]


class NetworkConfig:
    """Network configuration loaded from CSV file"""

    def __init__(self, csv_path: str):
        """
        Initialize NetworkConfig from CSV file

        Args:
            csv_path: Path to networks.csv file (e.g., "config/networks.csv")
        """
        self.csv_path = Path(csv_path)
        self.devices: Dict[int, DeviceInfo] = {}
        self._load_csv()

    def _load_csv(self):
        """Load and parse CSV file"""
        if not self.csv_path.exists():
            raise FileNotFoundError(f"Network CSV file not found: {self.csv_path}")

        logger.info(f"Loading network configuration from {self.csv_path}")

        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    device_id = int(row["ID"])
                    ip_address = row["IP"].strip() if row["IP"].strip() else None
                    # Parse target IDs from comma-separated string
                    target_ids_str = row["To"].strip()
                    target_ids = [int(tid.strip()) for tid in target_ids_str.split(",")] if target_ids_str else []

                    self.devices[device_id] = DeviceInfo(
                        device_id=device_id,
                        ip_address=ip_address,
                        target_ids=target_ids,
                    )
                except (KeyError, ValueError) as e:
                    logger.warning(f"Failed to parse row: {row}, error: {e}")
                    continue

        logger.info(f"Loaded {len(self.devices)} devices from CSV")

    def get_device_info(self, device_id: int) -> Optional[DeviceInfo]:
        """
        Get device information by ID

        Args:
            device_id: Device ID

        Returns:
            DeviceInfo if found, None otherwise
        """
        return self.devices.get(device_id)

    def get_ip_address(self, device_id: int) -> Optional[str]:
        """
        Get IP address for a device

        Args:
            device_id: Device ID

        Returns:
            IP address string if found and set, None otherwise
        """
        device = self.get_device_info(device_id)
        if device is None:
            logger.error(f"Device ID {device_id} not found in CSV")
            return None
        if device.ip_address is None:
            logger.error(f"Device ID {device_id} has no IP address set")
            return None
        return device.ip_address

    def get_target_ids(self, device_id: int) -> List[int]:
        """
        Get target device IDs for a device

        Args:
            device_id: Device ID

        Returns:
            List of target device IDs (empty list if not found)
        """
        device = self.get_device_info(device_id)
        if device is None:
            logger.error(f"Device ID {device_id} not found in CSV")
            return []
        return device.target_ids

    def resolve_targets(self, device_id: int, port: int = 8000) -> List[Dict[str, any]]:
        """
        Resolve target device IDs to host/port dictionaries

        Args:
            device_id: Source device ID
            port: OSC port number (default: 8000)

        Returns:
            List of target dictionaries with 'host', 'port', 'description'
        """
        target_ids = self.get_target_ids(device_id)
        targets = []

        for target_id in target_ids:
            ip_address = self.get_ip_address(target_id)
            if ip_address is None:
                logger.warning(f"Skipping target ID {target_id} (no IP address or not found)")
                continue

            targets.append(
                {
                    "host": ip_address,
                    "port": port,
                    "description": f"BI device {target_id}",
                }
            )

        logger.info(f"Resolved {len(targets)} targets for device ID {device_id}")
        return targets


def load_network_config(csv_path: str) -> NetworkConfig:
    """
    Convenience function to load network configuration

    Args:
        csv_path: Path to networks.csv file

    Returns:
        NetworkConfig instance
    """
    return NetworkConfig(csv_path)
