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

def cleanup_ng_words(text: str) -> str:
    """NGワードリストに基づいてテキストをクリーンアップする。

    preamble_keywords: テキスト先頭にある定型句を含む行を除去
    ng_words: テキスト全体から該当文字列を除去
    """
    data = _load_json("ngwords.json")

    # 1) preamble除去（先頭の定型句行をスキップ）
    preamble_kw = data.get("preamble_keywords", [])
    lines = text.splitlines()
    cleaned_lines = []
    past_preamble = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not past_preamble and any(kw in stripped for kw in preamble_kw):
            continue
        past_preamble = True
        cleaned_lines.append(stripped)
    text = "".join(cleaned_lines)

    # 2) ng_words除去（テキスト全体から文字列を削除）
    for ng in data.get("ng_words", []):
        text = text.replace(ng, "")

    # 3) 除去後の空白正規化
    text = text.strip()

    return text


# 後方互換：既存コードが LLM_SETTINGS / TTS_SETTINGS をimportしている箇所向け
LLM_SETTINGS = load_llm_settings()

TTS_SETTINGS = {
    "en": {"model": "melotts-en-us"},
    "ja": {"model": "melotts-ja-jp"},
    "zh": {"model": "melotts-zh-cn"},
    "fr": {"model": "melotts-en-us"},
}
