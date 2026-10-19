"""The tones a public corpus's speaker produced, read from the utterance's transcript with C0's
sandhi checker (`context = phrase`), or why the transcript does not settle them (ruling R122).

A transcript writes each syllable as a hanzi and numbered pinyin. Corpora differ in whether the
pinyin is the dictionary (citation) form or the spoken (surface) form, and some mix the two, so
each transcript is read on its own evidence:

- **Surface markers**: 一 written yí or yì, 不 written bú. Only sandhi makes them.
- **Citation markers**: tones the checker would change if they were the citation: 3-3 in a row,
  一 as yī or 不 as bù where sandhi applies. A spoken reading never has them.
- Both kinds in one transcript: dropped (`MIXED`).
- No citation marker: the transcript is the spoken reading. It must be a reading the checker gives
  for some citation it could be written from (一 and 不 restored, and each 2 that ends up before
  a 3 either a 2 or a sandhi'd 3), and none of those citations may have more than one native
  reading (R89: 2-2-3 could be 展览馆, said 2-2-3 or 3-2-3).
- Citation markers only: a per-recording transcript (written while listening to this recording,
  as AISHELL-3's are) should give the spoken tones, so 3-3 there means no sandhi was heard (a
  pause) or a dictionary tone slipped in: dropped. A script transcript (one per sentence, as
  THCHS-30's is) is read through the checker, with exactly one native reading, only third-tone
  sandhi inside a word (a pause can block it between words), and no 一 in its dictionary tone
  where sandhi applies (numbers, dates and ordinals keep yī, which the checker cannot tell).

Whatever the form, an utterance is dropped for erhua, for 一 or 不 before a neutral syllable
(their sandhi follows the neutral syllable's underlying tone, which the transcript does not give:
一下 is yí xia, which the checker cannot confirm), and for a second or third tone before its own
reduplication in the neutral tone (想想 is 2-5 or 3-5, 姐姐 3-5). The words whose neutral
syllable is lexically a third tone (哪里, 小姐) cannot be told from the text and stay a known
residual risk."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from itertools import product
from typing import Literal

from ..contracts.lects import lect_rules
from ..contracts.pinyin import PinyinError
from . import drops

RULES = lect_rules("cmn")
YI, BU = "一", "不"
ERHUA_HANZI = "儿"
MAX_SPLIT_SECONDS = 8  # 2s that may be sandhi'd 3s; more than this is treated as ambiguous

Form = Literal["surface", "citation", "either"]  # either: no tone that only one form writes


@dataclass(frozen=True)
class Transcript:
    """One utterance's transcript, one hanzi and one numbered pinyin token per syllable."""

    hanzi: tuple[str, ...]
    pinyin: tuple[str, ...]
    # The word each syllable belongs to (THCHS-30 segments words), or None when the corpus does not say.
    words: tuple[int, ...] | None
    # Written while listening to this recording (AISHELL-3), not once per sentence of the script.
    per_recording: bool


@dataclass(frozen=True)
class Reading:
    tones: tuple[str, ...]  # the tones the speaker produced (cmn pack tone ids)
    bases: tuple[str, ...]  # the toneless syllables
    form: Form  # how the transcript wrote them


@dataclass(frozen=True)
class Dropped:
    reason: str  # one of `drops`' reasons


def read(t: Transcript) -> Reading | Dropped:
    """The produced tones of `t`, or why it is dropped."""
    if not t.hanzi or len(t.hanzi) != len(t.pinyin) or (t.words is not None and len(t.words) != len(t.hanzi)):
        return Dropped(drops.MALFORMED)
    if not all(_is_hanzi(h) for h in t.hanzi):
        return Dropped(drops.NON_MANDARIN)
    parsed = _syllables(t)
    if isinstance(parsed, Dropped):
        return parsed
    tones, bases = parsed
    if (why := _neutral_ambiguity(t.hanzi, tones)) is not None:
        return Dropped(why)
    text = "".join(t.hanzi)
    as_citation = RULES.surface_options(tones, bases, "phrase", text)
    surface_marked = _surface_marked(t.hanzi, bases, tones)
    citation_marked = tones not in as_citation
    if surface_marked and citation_marked:
        return Dropped(drops.MIXED)
    if not citation_marked:
        why = _surface_problem(t.hanzi, bases, tones, text)
        form: Form = "surface" if surface_marked else "either"
        return Dropped(why) if why else Reading(tones, bases, form)
    return _through_the_checker(t, tones, bases, as_citation)


def _is_hanzi(h: str) -> bool:
    return len(h) == 1 and "CJK UNIFIED IDEOGRAPH" in unicodedata.name(h, "")


def _syllables(t: Transcript) -> tuple[tuple[str, ...], tuple[str, ...]] | Dropped:
    tones, bases = [], []
    for hanzi, token in zip(t.hanzi, t.pinyin, strict=True):
        low = token.lower()
        if low[:-1][-1:].isdigit() and low.endswith("r") or low.rstrip("12345") == "r":
            return Dropped(drops.ERHUA)  # an r after the tone digit (`hua1r`), or `r5`
        if not low[-1:].isdigit():
            return Dropped(drops.NO_TONE)
        try:
            (syllable,) = RULES.parse_pinyin(token)
        except (PinyinError, ValueError):
            return Dropped(drops.NON_MANDARIN)
        is_erhua_final = syllable.base.endswith("r") and syllable.base != "er"
        if is_erhua_final or (hanzi == ERHUA_HANZI and syllable.tone == "5"):
            return Dropped(drops.ERHUA)
        tones.append(syllable.tone)
        bases.append(syllable.base)
    return tuple(tones), tuple(bases)


def _neutral_ambiguity(hanzi: tuple[str, ...], tones: tuple[str, ...]) -> str | None:
    for i in range(len(tones) - 1):
        if tones[i + 1] != "5":
            continue
        if hanzi[i] in (YI, BU) and tones[i] != "5":
            return drops.NEUTRAL_YI_BU
        if tones[i] in ("2", "3") and hanzi[i + 1] == hanzi[i]:
            return drops.NEUTRAL_REDUPLICATION
    return None


def _is_yi_bu(hanzi: str, base: str) -> bool:
    return (hanzi, base) in ((YI, "yi"), (BU, "bu"))


def _surface_marked(hanzi: tuple[str, ...], bases: tuple[str, ...], tones: tuple[str, ...]) -> bool:
    return any(
        (h, b, t) in ((YI, "yi", "2"), (YI, "yi", "4"), (BU, "bu", "2")) for h, b, t in zip(hanzi, bases, tones)
    )


def _underlying(hanzi: tuple[str, ...], bases: tuple[str, ...], tones: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Per syllable, the citation tones a spoken tone could come from: 一 is yī, 不 is bù (unless
    written neutral, as in 看一看 and 对不起, which the checker leaves alone); a 2 in a run of 2s
    that ends right before a 3 may be a sandhi'd 3."""
    out: list[tuple[str, ...]] = []
    for i, (h, b, t) in enumerate(zip(hanzi, bases, tones)):
        if _is_yi_bu(h, b) and t != "5":
            out.append(("1",) if b == "yi" else ("4",))
        elif t == "2" and _run_of_twos_before_a_three(hanzi, bases, tones, i):
            out.append(("2", "3"))
        else:
            out.append((t,))
    return out


def _run_of_twos_before_a_three(
    hanzi: tuple[str, ...], bases: tuple[str, ...], tones: tuple[str, ...], i: int
) -> bool:
    j = i
    while j < len(tones) and tones[j] == "2" and not _is_yi_bu(hanzi[j], bases[j]):
        j += 1
    return j < len(tones) and tones[j] == "3"


def _surface_problem(hanzi: tuple[str, ...], bases: tuple[str, ...], tones: tuple[str, ...], text: str) -> str | None:
    """Why a transcript written as spoken tones cannot be taken as they stand: no citation explains
    them, or one that does has more than one native reading."""
    options = _underlying(hanzi, bases, tones)
    if sum(len(o) > 1 for o in options) > MAX_SPLIT_SECONDS:
        return drops.MANY_READINGS
    explained = False
    for citation in product(*options):
        readings = RULES.surface_options(citation, bases, "phrase", text)
        if tones in readings:
            explained = True
            if len(readings) > 1:
                return drops.MANY_READINGS
    return None if explained else drops.INCONSISTENT


def _through_the_checker(
    t: Transcript, tones: tuple[str, ...], bases: tuple[str, ...], readings: set[tuple[str, ...]]
) -> Reading | Dropped:
    """A transcript in citation form: spoken as the checker says, where that is safe."""
    if t.per_recording:
        third_tones = any(a == b == "3" for a, b in zip(tones, tones[1:]))
        return Dropped(drops.THIRD_TONES if third_tones else drops.YI_BU_DICTIONARY)
    if len(readings) > 1:
        return Dropped(drops.MANY_READINGS)
    (spoken,) = readings
    for i, (h, before, after) in enumerate(zip(t.hanzi, tones, spoken)):
        if h == YI and bases[i] == "yi" and before != after:
            return Dropped(drops.YI_BU_DICTIONARY)
        if before == "3" and after == "2" and (t.words is None or t.words[i] != t.words[i + 1]):
            return Dropped(drops.T3_ACROSS_WORDS)
    return Reading(spoken, bases, "citation")
