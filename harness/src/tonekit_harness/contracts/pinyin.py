"""Mandarin pinyin (cmn): tone-marked (`shuǐ`) or numbered (`shui3`) syllables into base syllable
and cmn pack tone id ("1" to "4"; no mark or `5` is the neutral tone, "5"). Erhua is a final `r`,
written after the mark or the digit (`huār`, `hua1r`). This is a cmn-specific module: the tone ids
are the cmn pack's (packs/cmn/cmn.toml)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

NEUTRAL = "5"

_MARK_TONES = {"̄": "1", "́": "2", "̌": "3", "̀": "4"}  # macron, acute, caron, grave
_DIAERESIS = "̈"
_VOWELS = frozenset("aeiouü")

_INITIALS = "zh|ch|sh|[bpmfdtnlgkhjqxrzcsyw]"
_FINALS = (
    "a o e ai ei ao ou an en ang eng ong er i ia io ie iao iu ian in iang ing iong "
    "u ua uo uai ui uan un uang ü üe üan ün ue"
).split()
# The syllable's shape, not a full table: it catches a typo like `shuui`, not an unused pairing.
_SYLLABLE = re.compile(
    rf"(?:{_INITIALS})?(?:{'|'.join(sorted(_FINALS, key=len, reverse=True))})r?"
)


# Syllables are separated by whitespace or an apostrophe: the straight one, or the U+2019 that
# phone keyboards type in its place.
_SEPARATORS = re.compile("[\\s'\u2019]+")
_RUN_TOGETHER = " (several syllables run together? separate them with spaces or ')"


class PinyinError(ValueError):
    """The pinyin could not be read; the message names the bad syllable."""


@dataclass(frozen=True)
class Syllable:
    text: str  # as written, e.g. "shuǐ" or "shui3"
    base: str  # lower case, no tone; the u-umlaut is "ü" (also written "v")
    tone: str  # a cmn tone id, "1" to "5"


def parse_pinyin(text: str) -> list[Syllable]:
    """The syllables of space-separated pinyin (an apostrophe also separates), tone-marked or
    numbered. Raises `PinyinError` naming the first syllable that is not pinyin."""
    tokens = [t for t in _SEPARATORS.split(text) if t]
    if not tokens:
        raise PinyinError(f"no syllables in {text!r}")
    syllables = []
    for token in tokens:
        try:
            syllables.append(_parse_syllable(token))
        except PinyinError as e:
            hint = _RUN_TOGETHER if _runs_together(token) else ""
            raise PinyinError(f"bad pinyin syllable {token!r} in {text!r}: {e}{hint}") from None
    return syllables


def tones_of(text: str) -> list[str]:
    """The tone id of each syllable of `text`."""
    return [s.tone for s in parse_pinyin(text)]


def _parse_syllable(token: str) -> Syllable:
    letters: list[str] = []
    marks: list[str] = []
    digits = ""
    chars = unicodedata.normalize("NFD", token).lower()
    for at, ch in enumerate(chars):
        if ch == "r" and len(digits) == 1 and at == len(chars) - 1:
            letters.append(ch)  # erhua after the tone digit: hua1r
        elif ch in _MARK_TONES:
            if not letters or letters[-1] not in _VOWELS:
                raise PinyinError("a tone mark must sit on a vowel")
            marks.append(_MARK_TONES[ch])
        elif ch == _DIAERESIS:
            if not letters or letters[-1] != "u":
                raise PinyinError("a diaeresis only goes on u")
            letters[-1] = "ü"
        elif "a" <= ch <= "z":
            if digits:
                raise PinyinError("the tone digit must end the syllable")
            letters.append("ü" if ch == "v" else ch)
        elif "0" <= ch <= "9":
            digits += ch
        else:
            raise PinyinError(f"unexpected character {ch!r}")
    return Syllable(token, _check_base("".join(letters)), _tone(marks, digits))


def _runs_together(token: str) -> bool:
    """Whether the token's letters split into two or more syllables (`yibeishui`, `nihao`), so that
    the likely mistake is a missing space."""
    letters = "".join(c for c in unicodedata.normalize("NFD", token).lower() if "a" <= c <= "z")
    return _splits(letters)


@lru_cache(maxsize=None)
def _splits(letters: str) -> bool:
    return any(
        _standalone(letters[:i]) and (_standalone(letters[i:]) or _splits(letters[i:]))
        for i in range(1, len(letters))
    )


def _standalone(piece: str) -> bool:
    """A syllable that can stand on its own in a run: with an initial, or starting on a, o or e (a
    bare i, u or ü final is written yi, wu, yu)."""
    return bool(_SYLLABLE.fullmatch(piece)) and (piece[0] in "aoe" or bool(re.match(_INITIALS, piece)))


def _check_base(base: str) -> str:
    if not _SYLLABLE.fullmatch(base):
        raise PinyinError(f"{base!r} is not a Mandarin syllable")
    return base


def _tone(marks: list[str], digits: str) -> str:
    if len(marks) > 1:
        raise PinyinError("more than one tone mark")
    if marks and digits:
        raise PinyinError("it has both a tone mark and a tone digit")
    if digits:
        if digits not in {"1", "2", "3", "4", "5"}:
            raise PinyinError(f"the tone digit must be one of 1 to 5, not {digits!r}")
        return digits
    return marks[0] if marks else NEUTRAL
