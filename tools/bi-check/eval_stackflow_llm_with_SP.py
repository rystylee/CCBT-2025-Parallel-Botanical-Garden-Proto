import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any
import random

from loguru import logger

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from api.llm import StackFlowLLMClient
from api.tts import StackFlowTTSClient

from bi.models import BIInputData
from bi.utils import P, H, VALS, make_random_soft_prefix_b64, make_soft_prefix_b64_constant

def load_config(path: Path) -> dict:
    """
    yaml / json どちらでも読めるようにする簡易ローダー
    """
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except Exception as e:
            raise RuntimeError("PyYAML is required to load .yaml config") from e
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    if path.suffix.lower() == ".json":
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    raise ValueError(f"Unsupported config format: {path.suffix}")


class BIController_TEST:
    """Controller for Botanical Intelligence cycle system (TEST harness)"""

    def __init__(self, config: dict):
        logger.info("Initialize BI Controller TEST...")
        self.config = config
        self.state = "STOPPED"
        self.input_buffer: List[BIInputData] = []
        self.generated_text = ""
        self.tts_text = ""

        # Initialize clients (OSCは使わない)
        self.llm_client = StackFlowLLMClient(config)
        self.tts_client = StackFlowTTSClient(config)

        logger.info("BI Controller TEST initialized")

    async def generate_sample(
        self,
        sample_text: str,
        *,
        lang: Optional[str] = None,
        soft_prefix_b64: Optional[str] = None,
        soft_prefix_len: int = P,
        play_tts: bool = False,
    ) -> Dict[str, Any]:
        """
        仮テキスト + softprefix で単発生成して確認する
        """
        if not sample_text or not sample_text.strip():
            raise ValueError("sample_text is empty")

        effective_lang = lang or self.config.get("common", {}).get("lang", "ja")
        effective_sp_b64 = soft_prefix_b64 or make_random_soft_prefix_b64()
        # v = random.choice(VALS)
        # logger.info(f"Selected soft prefix value: {v}")
        # effective_sp_b64 = make_soft_prefix_b64_constant(P, H, v)

        logger.info("=== BIController_TEST.generate_sample ===")
        logger.info(f"lang={effective_lang}, soft_prefix_len={soft_prefix_len}")
        logger.info(f"sample_text(len={len(sample_text)}): {sample_text!r}")
        logger.info(
            f"soft_prefix_b64(head): {effective_sp_b64[:24]}... (len={len(effective_sp_b64)})"
        )

        generated_text = await self.llm_client.generate_text(
            query=sample_text,
            lang=effective_lang,
            soft_prefix_b64=effective_sp_b64,
            soft_prefix_len=soft_prefix_len,
        )

        tts_text = sample_text + generated_text

        self.generated_text = generated_text
        self.tts_text = tts_text

        logger.info(f"generated_text: {generated_text!r}")
        logger.info(f"tts_text: {tts_text!r}")

        if play_tts:
            self.tts_client.speak(tts_text)

        return {
            "query": sample_text,
            "lang": effective_lang,
            "soft_prefix_b64": effective_sp_b64,
            "soft_prefix_len": soft_prefix_len,
            "generated_text": generated_text,
            "tts_text": tts_text,
        }


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--config",
        type=str,
        required=True,
        help="Path to config yaml/json (e.g. config/config.yaml)",
    )
    p.add_argument(
        "--text",
        type=str,
        default="温室の湿度が上がり、葉の表面に小さな水滴が現れた。土はまだ温かい。",
        help="Sample input text for generation",
    )
    p.add_argument("--lang", type=str, default=None, help="Override language (e.g. ja/en)")
    p.add_argument("--soft-prefix-b64", type=str, default=None, help="Fixed softprefix (base64)")
    p.add_argument("--soft-prefix-len", type=int, default=P, help="Softprefix length")
    p.add_argument("--tts", action="store_true", help="Play TTS with (input + generated)")
    p.add_argument("--n", type=int, default=1, help="How many times to run (for quick comparison)")
    return p


def main():
    args = build_argparser().parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path

    config = load_config(config_path)

    bi_test = BIController_TEST(config)

    async def _run():
        for i in range(args.n):
            logger.info(f"--- run {i+1}/{args.n} ---")
            result = await bi_test.generate_sample(
                args.text,
                lang=args.lang,
                soft_prefix_b64=args.soft_prefix_b64,
                soft_prefix_len=args.soft_prefix_len,
                play_tts=args.tts,
            )
            # 目視しやすいように最後に標準出力にも出す
            print("\n===== RESULT =====")
            print("query:", result["query"])
            print("lang:", result["lang"])
            print("soft_prefix_len:", result["soft_prefix_len"])
            print("soft_prefix_b64(head):", result["soft_prefix_b64"][:24] + "...")
            print("generated_text:", repr(result["generated_text"]))
            print("tts_text:", repr(result["tts_text"]))
            print("==================\n")

    asyncio.run(_run())


if __name__ == "__main__":
    main()
