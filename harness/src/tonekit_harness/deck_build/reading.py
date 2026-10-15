"""One reading of a text: what is shown, the dictionary pinyin, and the pinyin as spoken."""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts.lects import lect_rules
from ..contracts.pinyin import Syllable
from ..manifest import Context

RULES = lect_rules("cmn")


@dataclass(frozen=True)
class Reading:
    text: str  # simplified, what the card shows
    citation_pinyin: str  # dictionary form (yī bēi shuǐ)
    spoken_pinyin: str  # surface form with sandhi applied (yì bēi shuǐ)
    context: Context = "phrase"
    text_traditional: str | None = None  # same length as `text`, hand-entered (R74)

    def citation(self) -> list[Syllable]:
        return list(RULES.parse_pinyin(self.citation_pinyin))

    def spoken(self) -> list[Syllable]:
        return list(RULES.parse_pinyin(self.spoken_pinyin))
