import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from loguru import logger

from api.llm import StackFlowLLMClient
from api.tts import StackFlowTTSClient

class BIController_TEST:
    """Controller for Botanical Intelligence cycle system"""

    def __init__(self, config: dict):
        logger.info("Initialize BI Controller...")
        self.config = config
        self.state = "STOPPED"
        self.input_buffer: List[BIInputData] = []
        self.generated_text = ""
        self.tts_text = ""

        # Initialize clients
        self.llm_client = StackFlowLLMClient(config)
        self.tts_client = StackFlowTTSClient(config)

        logger.info("BI Controller initialized")


def main():
    bi_test = BIController_TEST()


if __name__ == "__main__":
    main()
