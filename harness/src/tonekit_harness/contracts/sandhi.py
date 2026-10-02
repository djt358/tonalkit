"""Mandarin tone sandhi (cmn): the surface tone sequences a citation reading may be spoken as.

The rules, on cmn pack tone ids:
- 一 (yī, tone 1): yí (2) before a tone 4, yì (4) before a 1, 2 or 3, yī (1) alone or last.
- 不 (bù, tone 4): bú (2) before a tone 4, otherwise bù.
- 一 after 第 is an ordinal and stays yī (1): 第一次 is 4-1-4, not 4-2-4. The hanzi must show 第
  right before 一, so this needs `text`.
- Third tones: a 3 before a 3 becomes 2. A run of three or more 3s is grouped by the reader, so
  every grouping is accepted: 展览馆 is 2-2-3 or 3-2-3.
- A final 3 of such a run may be neutral (5) in the word: 哪里 nǎ li, 姐姐 jiě jie, 奶奶 nǎi nai. The
  card writes the underlying tone (nǎ lǐ, citation 3-3) and shows the neutral one (nǎ li). The 3
  before that neutral syllable is then 3 (the half-third stays) or 2 (as if the next were still a
  3): 哪里 is 3-5 or 2-5, besides the regular 2-3. There is no lexicon here, so the neutral reading
  is accepted for the last 3 of any run of two or more third tones (it also admits 你好 as ní hao).
  A syllable that is neutral by citation (你们 nǐ men, citation 3-5) has no second reading.
Both 一 and 不 follow the *citation* tone of the next syllable. Neither changes before a neutral
tone (5), which has no underlying tone to follow; write the underlying tone in the pinyin.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from functools import lru_cache
from itertools import groupby, product

from ..manifest import Context

_TONES = frozenset("12345")


def surface_options(
    citation_tones: Sequence[str],
    syllables: Sequence[str],
    context: Context,
    text: str | None = None,
) -> set[tuple[str, ...]]:
    """The acceptable surface tone sequences of a reading with these citation tones.

    `syllables` are the toneless base syllables (`Syllable.base`), which tell 一 (yi, tone 1) and
    不 (bu, tone 4) from the other words of the same sound. `text` is the hanzi shown; when it has
    one character per syllable, 衣 (yī) and 步 (bù) are told apart from 一 and 不 by it, otherwise
    the sound alone decides. `context="isolated"` is the citation sequence alone, with no sandhi."""
    _check_input(citation_tones, syllables, context)
    citation = tuple(citation_tones)
    if context == "isolated":
        return {citation}
    hanzi = _hanzi_per_syllable(text, len(citation))
    fixed = _yi_and_bu(citation, syllables, hanzi)
    return {
        _assemble(fixed, runs)
        for runs in product(*(_run_options(n) | _neutral_final_options(n) for _, n in _runs(fixed)))
    }


def _check_input(citation_tones: Sequence[str], syllables: Sequence[str], context: str) -> None:
    if len(citation_tones) != len(syllables):
        raise ValueError(f"{len(citation_tones)} citation tones but {len(syllables)} syllables")
    for tone in citation_tones:
        if tone not in _TONES:
            raise ValueError(f"unknown tone id {tone!r}")
    if context not in ("phrase", "isolated"):
        raise ValueError(f"unknown context {context!r}; use 'phrase' or 'isolated'")


def _hanzi_per_syllable(text: str | None, n: int) -> list[str] | None:
    if text is None:
        return None
    chars = [c for c in text if "CJK UNIFIED IDEOGRAPH" in unicodedata.name(c, "")]
    return chars if len(chars) == n else None


def _yi_and_bu(
    citation: tuple[str, ...], syllables: Sequence[str], hanzi: list[str] | None
) -> list[str | None]:
    """The tones after 一 and 不 sandhi; each position of a third-tone run is None, to be filled
    in by `_assemble`."""
    out: list[str | None] = list(citation)
    for i, tone in enumerate(citation):
        nxt = citation[i + 1] if i + 1 < len(citation) else None
        word = hanzi[i] if hanzi else None
        if syllables[i] == "yi" and tone == "1" and word in (None, "一"):
            ordinal = i > 0 and hanzi is not None and hanzi[i - 1] == "第"
            out[i] = tone if ordinal else {"4": "2", "1": "4", "2": "4", "3": "4"}.get(nxt or "", tone)
        elif syllables[i] == "bu" and tone == "4" and word in (None, "不"):
            out[i] = "2" if nxt == "4" else tone
        elif tone == "3":
            out[i] = None
    return out


def _runs(tones: list[str | None]) -> list[tuple[int, int]]:
    """(start, length) of each run of third tones (None entries)."""
    runs, i = [], 0
    for is_third, group in groupby(tones, key=lambda t: t is None):
        n = len(list(group))
        if is_third:
            runs.append((i, n))
        i += n
    return runs


def _assemble(fixed: list[str | None], run_tones: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    out = list(fixed)
    for (start, n), tones in zip(_runs(fixed), run_tones, strict=True):
        out[start : start + n] = tones
    return tuple(t for t in out if t is not None)


@lru_cache(maxsize=None)
def _run_options(n: int) -> frozenset[tuple[str, ...]]:
    """Every surface reading of n third tones in a row: one per way to bracket the run into
    prosodic groups, where joining two groups turns the left group's final 3 into 2 if the right
    group starts on a 3. n=2 gives 2-3; n=3 gives 2-2-3 and 3-2-3."""
    if n == 1:
        return frozenset({("3",)})
    return frozenset(
        _join(left, right)
        for k in range(1, n)
        for left in _run_options(k)
        for right in _run_options(n - k)
    )


@lru_cache(maxsize=None)
def _neutral_final_options(n: int) -> frozenset[tuple[str, ...]]:
    """The readings of a run of n >= 2 third tones whose last syllable is neutral (5): the rest of
    the run reads as a run of n - 1, and the third tone before the neutral stays 3 or becomes 2."""
    if n < 2:
        return frozenset()
    return frozenset(
        variant
        for left in _run_options(n - 1)
        for variant in (left + ("5",), left[:-1] + ("2", "5"))
    )


def _join(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    if left[-1] == "3" and right[0] == "3":
        left = left[:-1] + ("2",)
    return left + right
