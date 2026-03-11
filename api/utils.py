import json
import os
import re

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
    """ngwords.json に基づいてLLM生成テキストをクリーンアップする。

    処理順:
      1. 改行をフラット化
      2. drop_line_patterns: マッチ行を丸ごと除去
      3. preamble_keywords: 先頭の定型句行をスキップ
      4. strip_prefixes: 先頭の定型プレフィックスを正規表現で除去
      5. strip_symbols: Markdown残骸などを全体から除去
      6. strip_punctuation: 句読点を除去
      7. 空白正規化
    """
    data = _load_json("ngwords.json")

    # 0) 改行 → スペースで一旦フラット化（\n が混じっている）
    text = text.replace("\\n", "\n").replace("\r", "")

    # 1) drop_line_patterns: マッチ行を丸ごと除去
    drop_patterns = data.get("drop_line_patterns", [])
    if drop_patterns:
        lines = text.splitlines()
        kept = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if any(re.search(pat, stripped) for pat in drop_patterns):
                continue
            kept.append(stripped)
        text = "".join(kept)

    # 2) preamble_keywords: 先頭の定型句をスキップ
    preamble_kw = data.get("preamble_keywords", [])
    # 先頭から定型句を含むチャンクを除去（改行なし状態なので先頭マッチ）
    changed = True
    while changed:
        changed = False
        for kw in preamble_kw:
            if text.startswith(kw):
                text = text[len(kw):]
                changed = True

    # 3) strip_prefixes: 先頭プレフィックスを正規表現で除去
    for pat in data.get("strip_prefixes", []):
        text = re.sub(r"^" + pat, "", text)

    # 4) strip_symbols: Markdown残骸などを全体から除去
    for sym in data.get("strip_symbols", []):
        text = text.replace(sym, "")

    # 5) strip_punctuation: 句読点除去
    for p in data.get("strip_punctuation", []):
        text = text.replace(p, "")

    # 6) 空白正規化
    text = re.sub(r"\s+", " ", text).strip()

    return text


# 後方互換：既存コードが LLM_SETTINGS / TTS_SETTINGS をimportしている箇所向け
LLM_SETTINGS = load_llm_settings()

TTS_SETTINGS = {
    "en": {"model": "melotts-en-us"},
    "ja": {"model": "melotts-ja-jp"},
    "zh": {"model": "melotts-zh-cn"},
    "fr": {"model": "melotts-en-us"},
}
