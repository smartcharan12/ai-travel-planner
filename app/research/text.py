"""Small text helpers shared by normalization and grounding."""

from __future__ import annotations

import re
import unicodedata

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def clean_text(text: str) -> str:
    """Remove control characters and collapse all whitespace to single spaces."""
    return " ".join(_CONTROL_CHARS.sub(" ", text).split())


def fold(text: str) -> str:
    """Lower-case, strip accents and punctuation: 'Café  Mambo's' -> 'cafe mambo s'.

    Used to compare an LLM-written name with source text without being
    fooled by case, accents or punctuation differences.
    """
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(_NON_ALNUM.sub(" ", without_accents).split())


def contains_phrase(haystack: str, needle: str) -> bool:
    """True if ``needle`` appears in ``haystack`` as whole words, after folding."""
    folded_needle = fold(needle)
    if not folded_needle:
        return False
    return f" {folded_needle} " in f" {fold(haystack)} "


def truncate(text: str, max_chars: int) -> str:
    """Cut at a word boundary so the LLM never sees half a word."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0]
    return cut + " …"
