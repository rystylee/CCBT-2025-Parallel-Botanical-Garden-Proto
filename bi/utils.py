import json
import os

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")


def _load_json(filename: str) -> dict:
    path = os.path.join(_CONFIG_DIR, filename)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_llm_settings() -> dict:
    config = _load_json("config.json")
    return config.get("llm_settings", {})


def load_ng_words() -> list[str]:
    data = _load_json("ngwords.json")
    return data.get("preamble_keywords", [])


# 後方互換：既存コードが LLM_SETTINGS / TTS_SETTINGS をimportしている箇所向け
LLM_SETTINGS = load_llm_settings()

TTS_SETTINGS = {
    "en": {"model": "melotts-en-us"},
    "ja": {"model": "melotts-ja-jp"},
    "zh": {"model": "melotts-zh-cn"},
    "fr": {"model": "melotts-en-us"},
}
