from dataclasses import dataclass


@dataclass
class BIInputData:
    """Data structure for BI input with timestamp"""

    timestamp: float
    text: str
    source_type: str  # "HUMAN" or "BI"
    lang: str
