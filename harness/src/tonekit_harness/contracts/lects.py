"""The per-lect rules the contracts need, behind one small interface. A new lect registers its
own `LectRules` in `_LECTS`; nothing outside this module names a lect's tones or accents."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .pinyin import Syllable, parse_pinyin
from .sandhi import surface_options


class LectError(ValueError):
    """There are no rules for the lect."""


@dataclass(frozen=True)
class LectRules:
    # romanisation -> syllables with tone ids (the pack's)
    parse_pinyin: Callable[[str], Sequence[Syllable]]
    # (citation tones, base syllables, context, text) -> acceptable surface tone sequences
    surface_options: Callable[..., set[tuple[str, ...]]]
    # `grew_up_hearing` (None if unknown) -> the pack accent id a speaker is graded against
    default_accent: Callable[[str | None], str]


def _cmn_default_accent(grew_up_hearing: str | None) -> str:
    return "cmn-TW" if grew_up_hearing == "taiwan" else "cmn-standard"


_LECTS = {
    "cmn": LectRules(
        parse_pinyin=parse_pinyin,
        surface_options=surface_options,
        default_accent=_cmn_default_accent,
    ),
}


def lect_rules(lect: str) -> LectRules:
    try:
        return _LECTS[lect]
    except KeyError:
        known = ", ".join(sorted(_LECTS))
        raise LectError(f"no rules for lect {lect!r} (known: {known})") from None
