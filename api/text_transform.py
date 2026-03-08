"""
Text transformation module for TTS preprocessing.

Converts input text to hiragana and applies vowel elongation effects:
  - "dash":  長音記号で伸ばす  きょーーーうーーーわーーー
  - "vowel": 母音を繰り返す    きょおおおおううううわあああ
  - "mixed": 大小母音を混合    きょぉぉおぉうぅぅうわぁぁあ
  - "off":   変換なし
"""

import random
import re
from typing import Optional

from loguru import logger

# ============================================================
# Hiragana vowel mapping
# ============================================================

# Each hiragana mora → its trailing vowel
MORA_TO_VOWEL = {}

_VOWEL_GROUPS = {
    "あ": list("あかさたなはまやらわがざだばぱ"),
    "い": list("いきしちにひみりぎじぢびぴ"),
    "う": list("うくすつぬふむゆるぐずづぶぷ"),
    "え": list("えけせてねへめれげぜでべぺ"),
    "お": list("おこそとのほもよろをごぞどぼぽ"),
}

for vowel, moras in _VOWEL_GROUPS.items():
    for m in moras:
        MORA_TO_VOWEL[m] = vowel

# Small vowels mapping
VOWEL_TO_SMALL = {
    "あ": "ぁ",
    "い": "ぃ",
    "う": "ぅ",
    "え": "ぇ",
    "お": "ぉ",
}

# Characters that should not be elongated
SKIP_CHARS = set("んっ、。！？・…ー 　\n\r\t")


# ============================================================
# Kanji → Hiragana conversion
# ============================================================

def _try_import_pykakasi():
    """Try to import pykakasi for kanji→hiragana conversion."""
    try:
        import pykakasi
        kakasi = pykakasi.kakasi()
        kakasi.setMode("H", "H")  # Hiragana → Hiragana
        kakasi.setMode("K", "H")  # Katakana → Hiragana
        kakasi.setMode("J", "H")  # Kanji → Hiragana
        kakasi.setMode("E", "a")  # ASCII → as-is
        converter = kakasi.getConverter()
        return converter
    except (ImportError, AttributeError):
        pass

    # Try newer pykakasi API
    try:
        import pykakasi
        kks = pykakasi.Kakasi()
        return kks
    except (ImportError, AttributeError):
        pass

    return None


_KAKASI_CONVERTER = None
_KAKASI_INIT_DONE = False


def to_hiragana(text: str) -> str:
    """
    Convert text to hiragana.
    Uses pykakasi if available, otherwise does basic katakana→hiragana
    and passes through kanji unchanged.
    """
    global _KAKASI_CONVERTER, _KAKASI_INIT_DONE

    if not _KAKASI_INIT_DONE:
        _KAKASI_CONVERTER = _try_import_pykakasi()
        _KAKASI_INIT_DONE = True
        if _KAKASI_CONVERTER:
            logger.info("[text_transform] pykakasi available for kanji→hiragana")
        else:
            logger.info("[text_transform] pykakasi not found, using katakana→hiragana only")

    if _KAKASI_CONVERTER is not None:
        try:
            # Try newer API first
            if hasattr(_KAKASI_CONVERTER, "convert"):
                result_items = _KAKASI_CONVERTER.convert(text)
                return "".join(item["hira"] for item in result_items)
            # Older API
            elif hasattr(_KAKASI_CONVERTER, "do"):
                return _KAKASI_CONVERTER.do(text)
        except Exception as e:
            logger.warning(f"[text_transform] pykakasi failed: {e}, using fallback")

    # Fallback: katakana → hiragana only
    return _katakana_to_hiragana(text)


def _katakana_to_hiragana(text: str) -> str:
    """Convert katakana to hiragana (0x60 offset in Unicode)."""
    result = []
    for ch in text:
        cp = ord(ch)
        # Full-width katakana range: 0x30A1-0x30F6
        if 0x30A1 <= cp <= 0x30F6:
            result.append(chr(cp - 0x60))
        # Small katakana: 0x30A1 area
        elif 0x30F7 <= cp <= 0x30FA:
            result.append(chr(cp - 0x60))
        else:
            result.append(ch)
    return "".join(result)


# ============================================================
# Vowel elongation
# ============================================================

def elongate_dash(
    text: str,
    probability: float = 0.5,
    length_min: int = 2,
    length_max: int = 5,
    seed: Optional[int] = None,
) -> str:
    """
    Add long vowel marks (ー) after random morae.
    Example: きょうは → きょーーーうーーーはーーー
    """
    rng = random.Random(seed)
    result = []

    for ch in text:
        result.append(ch)
        if ch in MORA_TO_VOWEL and ch not in SKIP_CHARS:
            if rng.random() < probability:
                n = rng.randint(length_min, length_max)
                result.append("ー" * n)

    return "".join(result)


def elongate_vowel(
    text: str,
    probability: float = 0.5,
    length_min: int = 2,
    length_max: int = 5,
    seed: Optional[int] = None,
) -> str:
    """
    Repeat the trailing vowel of random morae.
    Example: きょうは → きょおおおおううううはあああ
    """
    rng = random.Random(seed)
    result = []

    for ch in text:
        result.append(ch)
        vowel = MORA_TO_VOWEL.get(ch)
        if vowel and ch not in SKIP_CHARS:
            if rng.random() < probability:
                n = rng.randint(length_min, length_max)
                result.append(vowel * n)

    return "".join(result)


def elongate_mixed(
    text: str,
    probability: float = 0.5,
    length_min: int = 3,
    length_max: int = 6,
    seed: Optional[int] = None,
) -> str:
    """
    Mix small and large vowels for a whispery, organic elongation.
    Example: きょうは → きょぉぉおぉうぅぅうわぁぁあ
    """
    rng = random.Random(seed)
    result = []

    for ch in text:
        result.append(ch)
        vowel = MORA_TO_VOWEL.get(ch)
        if vowel and ch not in SKIP_CHARS:
            if rng.random() < probability:
                n = rng.randint(length_min, length_max)
                small = VOWEL_TO_SMALL.get(vowel, vowel)
                # Generate pattern: mix of small and large
                pattern = []
                for j in range(n):
                    if rng.random() < 0.6:
                        pattern.append(small)
                    else:
                        pattern.append(vowel)
                # Always end with full vowel for clarity
                pattern[-1] = vowel
                result.append("".join(pattern))

    return "".join(result)


# ============================================================
# Main transform function
# ============================================================

def transform_text(
    text: str,
    to_hira: bool = True,
    elongation_mode: str = "off",
    elongation_probability: float = 0.5,
    elongation_length_min: int = 2,
    elongation_length_max: int = 5,
    seed: Optional[int] = None,
) -> str:
    """
    Apply text transformations for TTS.

    Args:
        text: Input text
        to_hira: Convert to hiragana
        elongation_mode: "dash" | "vowel" | "mixed" | "off"
        elongation_probability: Chance each mora gets elongated (0-1)
        elongation_length_min: Minimum elongation repeat count
        elongation_length_max: Maximum elongation repeat count
        seed: Random seed for reproducible elongation

    Returns:
        Transformed text
    """
    original = text
    result = text

    # Step 1: Hiragana conversion
    if to_hira:
        result = to_hiragana(result)

    # Step 2: Elongation
    if elongation_mode == "dash":
        result = elongate_dash(
            result, elongation_probability,
            elongation_length_min, elongation_length_max, seed,
        )
    elif elongation_mode == "vowel":
        result = elongate_vowel(
            result, elongation_probability,
            elongation_length_min, elongation_length_max, seed,
        )
    elif elongation_mode == "mixed":
        result = elongate_mixed(
            result, elongation_probability,
            elongation_length_min, elongation_length_max, seed,
        )

    if result != original:
        logger.info(f"[text_transform] '{original[:30]}...' → '{result[:50]}...'")

    return result
