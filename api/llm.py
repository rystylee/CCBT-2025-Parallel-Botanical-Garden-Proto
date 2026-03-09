import asyncio
import json

import argostranslate.translate
from loguru import logger

from api.utils import LLM_SETTINGS
from stackflow.utils import (
    close_tcp_connection,
    create_tcp_connection,
    exit_session,
    parse_setup_response,
    receive_response,
    send_json,
)


class StackFlowLLMClient:
    def __init__(self, config: dict):
        self.config = config
        self.set_params(config)

        self.sock = create_tcp_connection("localhost", 10001)
        self.llm_work_id = self._init()

    def __del__(self):
        deinit_data = self._create_deinit_data()
        exit_session(self.sock, deinit_data)
        close_tcp_connection(self.sock)

    def set_params(self, config: dict):
        lang = config.get("common").get("lang")
        self.lang = lang
        # self.model = LLM_SETTINGS.get(lang).get("model")
        # self.max_tokens = config.get("stack_flow_llm").get("max_tokens")
        # self.system_prompt = LLM_SETTINGS.get(lang).get("system_prompt")
        # self.instruction_prompt = LLM_SETTINGS.get(lang).get("instruction_prompt")
        # LLM always uses Japanese prompts (TinySwallow is Japanese-only)
        ja_settings = LLM_SETTINGS.get("ja")
        self.model = ja_settings.get("model")
        self.max_tokens = config.get("stack_flow_llm").get("max_tokens")
        self.system_prompt = ja_settings.get("system_prompt")
        self.instruction_prompt = ja_settings.get("instruction_prompt")

        logger.info("[LLM info]")
        logger.info(f"lang: {lang}")
        logger.info(f"model: {self.model}")
        logger.info(f"max_tokens: {self.max_tokens}")
        logger.info(f"system_prompt: {self.system_prompt}")
        logger.info(f"instruction_prompt: {self.instruction_prompt}")
        logger.info("")

    async def generate_text(
        self, query: str, soft_prefix_b64: str | None = None, soft_prefix_len: int = 0
    ) -> str:
        logger.info(f"query: {query}")

        # Input is always Japanese, pass directly to LLM
        prompt = self.instruction_prompt + query
        logger.info(f"prompt: {prompt}")
        if soft_prefix_b64 is not None:
            sp_val = self._decode_soft_prefix_val(soft_prefix_b64)
            logger.info(f"soft_prefix: val={sp_val:.6f} len={soft_prefix_len}")

        send_data = self._create_send_data(prompt, soft_prefix_b64, soft_prefix_len)
        output = await asyncio.to_thread(self._inference_sync, send_data)

        output = self._postprocess(output, query)

        # Post-generation: translate Japanese output to device language
        if self.lang != "ja" and output:
            ja_text = output
            output = await asyncio.to_thread(self._translate_sync, output)
            logger.info(f"Post-translate ja->({self.lang}): {ja_text} -> {output}")

        return output

    def _inference_sync(self, send_data: dict) -> str:
        """Run blocking TCP inference in a thread (called via asyncio.to_thread)."""
        send_json(self.sock, send_data)

        output = ""
        while True:
            response = receive_response(self.sock)
            response_data = json.loads(response)

            data = self._parse_inference_response(response_data)
            if data is None:
                break

            delta = data.get("delta")
            finish = data.get("finish")
            output += delta
            logger.debug(delta)

            if finish:
                break

        return output

    @staticmethod
    def _decode_soft_prefix_val(b64: str) -> float:
        """Decode the first BF16 value from a soft_prefix base64 string."""
        import base64, struct
        try:
            raw = base64.b64decode(b64)
            u16 = struct.unpack("<H", raw[:2])[0]
            # BF16 -> float32: shift left 16 bits
            f32 = struct.unpack("<f", struct.pack("<I", u16 << 16))[0]
            return f32
        except Exception:
            return -1.0

    def _init(self) -> str:
        logger.info("Setup LLM...")
        init_data = self._create_init_data()
        llm_work_id = self._setup(self.sock, init_data)
        logger.debug(f"llm_work_id: {llm_work_id}")
        logger.info("Setup LLM finished.")
        return llm_work_id

    def _setup(self, sock, init_data) -> str:
        sent_request_id = init_data["request_id"]
        send_json(sock, init_data)
        response = receive_response(sock)
        response_data = json.loads(response)
        logger.debug(f"llm response: {response_data}")
        return parse_setup_response(response_data, sent_request_id)

    def _parse_inference_response(self, response_data: dict) -> str:
        error = response_data.get("error")
        if error and error.get("code") != 0:
            print(f"Error Code: {error['code']}, Message: {error['message']}")
            return None

        return response_data.get("data")

    def _create_init_data(self) -> dict:
        return {
            "request_id": "llm_001",
            "work_id": "llm",
            "action": "setup",
            "object": "llm.setup",
            "data": {
                "model": self.model,
                "response_format": "llm.utf-8.stream",
                "input": "llm.utf-8.stream",
                "enoutput": True,
                "max_token_len": self.max_tokens,
                "prompt": self.system_prompt,
            },
        }

    def _create_deinit_data(self) -> dict:
        return {"request_id": "llm_exit", "work_id": self.llm_work_id, "action": "exit"}

    def _create_send_data(self, prompt: str, soft_prefix_b64: str | None = None, soft_prefix_len: int = 0) -> dict:
        data_obj = {"delta": prompt, "index": 0, "finish": True}
        if soft_prefix_b64 is not None:
            data_obj["soft_prefix"] = {"len": int(soft_prefix_len), "data_b64": soft_prefix_b64}

        return {
            "request_id": "llm_001",
            "work_id": self.llm_work_id,
            "action": "inference",
            "object": "llm.utf-8.stream",
            "data": data_obj,
        }

    def _translate_sync(self, query: str) -> str:
        """Translate from Japanese to device language via English pivot (called via asyncio.to_thread)."""
        try:
            en_text = argostranslate.translate.translate(query, from_code="ja", to_code="en")
            logger.debug(f"Pivot translation ja->en: {en_text}")
        except Exception as e:
            logger.error(f"Translation ja->en failed: {e}, using original")
            return query

        if self.lang == "en":
            return en_text

        try:
            result = argostranslate.translate.translate(en_text, from_code="en", to_code=self.lang)
            return result
        except Exception as e:
            logger.warning(f"Translation en->{self.lang} failed: {e}, falling back to English")
            return en_text

    def _postprocess(self, text: str, query: str = "") -> str:
        from api.utils import load_ng_words

        # Remove role prefix (e.g. "詩人:")
        if ":" in text:
            idx = text.find(":")
            text = text[idx + 1:]

        # Remove preamble lines, collect all meaningful lines
        preamble_keywords = load_ng_words()
        cleaned = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "":
                continue
            if not cleaned and any(kw in stripped for kw in preamble_keywords):
                continue
            cleaned += stripped

        # Remove input echo before truncation
        cleaned = self._remove_input_echo(cleaned, query)

        return self._truncate(cleaned)

    def _remove_input_echo(self, output: str, query: str) -> str:
        """Remove input echo from the beginning of LLM output."""
        if not output or not query:
            return output

        original = output

        # 1. Full prefix match: query="この森には" output="この森には、古く..." → "古く..."
        if output.startswith(query):
            output = output[len(query):]

        # 2. Partial overlap: query="この森には" output="森には闇が" → "闇が"
        else:
            for i in range(1, len(query)):
                suffix = query[i:]
                if output.startswith(suffix):
                    output = output[len(suffix):]
                    break

        # Strip leading punctuation left after removal
        output = output.lstrip("、。，．,. \t　*")

        if output != original:
            logger.info(f"Removed input echo: '{original}' -> '{output}'")

        return output

    # --- Character limit per language (ja 10 chars ≈ en/fr 25 chars ≈ fa/ar 20 chars) ---
    _MAX_CHARS = {"ja": 10, "zh": 10, "en": 25, "fr": 25, "fa": 20, "ar": 20}
    _BREAKS_CJK = ["。", "、", "　", " ", "が", "の", "に", "を", "で", "と", "は", "も"]
    _BREAKS_LATIN = [" ", ",", ".", ";"]
    _BREAKS_RTL = [" ", "،", ".", "؛"]

    def _get_max_chars(self) -> int:
        cfg = self.config.get("stack_flow_llm", {}).get("max_output_chars", {})
        return cfg.get(self.lang, self._MAX_CHARS.get(self.lang, 25))

    def _truncate(self, text: str) -> str:
        """Truncate text to appropriate length with natural break points."""
        max_chars = self._get_max_chars()
        if len(text) <= max_chars:
            return text

        cut = text[:max_chars]

        if self.lang in ("ja", "zh"):
            breaks = self._BREAKS_CJK
        elif self.lang in ("fa", "ar"):
            breaks = self._BREAKS_RTL
        else:
            breaks = self._BREAKS_LATIN

        # Find last natural break point (not too early)
        min_pos = max_chars // 3
        best = -1
        for sep in breaks:
            idx = cut.rfind(sep)
            if idx > min_pos:
                best = max(best, idx + len(sep))

        if best > 0:
            return cut[:best].strip()
        return cut.strip()
