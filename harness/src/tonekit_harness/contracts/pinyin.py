"""Mandarin pinyin (cmn): tone-marked (`shuǐ`) or numbered (`shui3`) syllables into base syllable
and cmn pack tone id ("1" to "4"; no mark or `5` is the neutral tone, "5"). This is a cmn-specific
module: the tone ids are the cmn pack's (packs/cmn/cmn.toml)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

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
    tokens = [t for t in re.split(r"[\s']+", text) if t]
    if not tokens:
        raise PinyinError(f"no syllables in {text!r}")
    syllables = []
    for token in tokens:
        try:
            syllables.append(_parse_syllable(token))
        except PinyinError as e:
            raise PinyinError(f"bad pinyin syllable {token!r} in {text!r}: {e}") from None
    return syllables


def tones_of(text: str) -> list[str]:
    """The tone id of each syllable of `text`."""
    return [s.tone for s in parse_pinyin(text)]


def _parse_syllable(token: str) -> Syllable:
    letters: list[str] = []
    marks: list[str] = []
    digits = ""
    for ch in unicodedata.normalize("NFD", token).lower():
        if ch in _MARK_TONES:
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
