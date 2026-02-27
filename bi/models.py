from dataclasses import dataclass


@dataclass
class BIInputData:
    """Data structure for BI input with relay count and soft prefix"""

    soft_prefix_b64: str
    relay_count: int
    text: str
