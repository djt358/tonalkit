"""Pinyin written in words ("kāfēi") into one syllable per token ("kā fēi"), which is what the
contract parses. DJ's g_measure table may write it either way; the splitting is only whitespace, and
the gate checks the result against the number of characters, so a wrong split is reported, not used."""

from __future__ import annotations

import re
import unicodedata

from .reading import RULES

_LONGEST_SYLLABLE = 8  # letters and a tone mark: "zhuāng", "chuáng"


def _is_syllable(piece: str) -> bool:
    try:
        return len(RULES.parse_pinyin(piece)) == 1
    except ValueError:
        return False


def split_token(token: str) -> list[str] | None:
    """The fewest valid syllables that spell `token`, or None if it cannot be spelt as syllables."""
    best: list[list[str] | None] = [None] * (len(token) + 1)
    best[0] = []
    for end in range(1, len(token) + 1):
        for start in range(max(0, end - _LONGEST_SYLLABLE), end):
            head = best[start]
            if head is not None and _is_syllable(token[start:end]):
                if best[end] is None or len(head) + 1 < len(best[end]):
                    best[end] = [*head, token[start:end]]
    return best[len(token)]


def space_pinyin(pinyin: str) -> str:
    """`pinyin` with every token that is not a single syllable split into syllables; text that
    cannot be split is left as it is, for the contract to name."""
    tokens: list[str] = []
    for token in re.split(r"[\s']+", unicodedata.normalize("NFC", pinyin)):
        if not token:
            continue
        pieces = None if _is_syllable(token) else split_token(token)
        tokens += pieces if pieces else [token]
    return " ".join(tokens)
