"""Tone-marked pinyin from a base syllable and a cmn tone id: the inverse of `contracts.pinyin`
(which only reads it). Neutral tones are unmarked. The tests read every rendering back with
`parse_pinyin`."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence

_MARKS = {"1": "\u0304", "2": "\u0301", "3": "\u030c", "4": "\u0300"}  # macron, acute, caron, grave
_VOWELS = "aeiouü"


def _marked_index(base: str) -> int:
    """Where the tone mark goes: a, then e, then the o of ou, otherwise the last vowel
    (the second of iu, ui, uo and the like)."""
    for vowel in "ae":
        if vowel in base:
            return base.index(vowel)
    if "ou" in base:
        return base.index("ou")
    return max(i for i, ch in enumerate(base) if ch in _VOWELS)


def render_syllable(base: str, tone: str) -> str:
    """`render_syllable("shui", "3")` is "shuǐ"; tone "5" gives the base unchanged."""
    if tone == "5":
        return base
    if tone not in _MARKS:
        raise ValueError(f"unknown tone id {tone!r}")
    if not any(ch in _VOWELS for ch in base):
        raise ValueError(f"{base!r} has no vowel to carry a tone mark")
    i = _marked_index(base)
    return unicodedata.normalize("NFC", base[: i + 1] + _MARKS[tone] + base[i + 1 :])


def render(bases: Sequence[str], tones: Sequence[str]) -> str:
    """Space-separated tone-marked syllables."""
    if len(bases) != len(tones):
        raise ValueError(f"{len(bases)} syllables but {len(tones)} tones")
    return " ".join(render_syllable(b, t) for b, t in zip(bases, tones, strict=True))
