from dataclasses import dataclass


@dataclass
class BIInputData:
    """Data structure for BI input with relay count"""

    relay_count: int
    text: str
    source_type: str  # "HUMAN" or "BI"
    lang: str
