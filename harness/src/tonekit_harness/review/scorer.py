"""The scorer's view of a clip, from a `tkh eval --results` file, measured against what the card
asks to be said (not against the clip's current label: the page is about whether the label is
right).

Per syllable: the tone tonekit heard (its most likely tone, when that reaches the pack's
`heard_threshold`; otherwise none: the scorer is unsure) and p_correct, the probability it gives
the intended tone. The *doubt* about a syllable's label is how likely the scorer thinks the card's
tone was not said: 1 − p_correct where the card asks for the intended tone, p_correct where it
asks for an error tone. A syllable with no nucleus has no evidence and no doubt.

A clip is in one of five groups, in page order:
- TWIN: on a syllable where the clip's card and its pair twin differ, the scorer heard the twin's
  tone, or, on an error card (whose twin there has the intended tone), it gives the intended tone
  at least even odds without hearing any tone confidently: an error card read as the correct
  word, or a correct card read as the error word. This is the most specific sign of a wrong
  label; the scorer's general weaknesses (a creaky final T4, a shallow reduced T4) spread over
  every card and say less;
- DISAGREES: some other syllable was heard, confidently, as another tone than the card's;
- UNSURE: the scorer doubts a syllable (doubt at least 0.5), or could not measure one, or left
  the clip unscored;
- NOT_GRADED: the results file has no entry for the clip;
- AGREES: the rest."""

from __future__ import annotations

from dataclasses import dataclass

from ..eval_results import ClipResult, SyllableResult
from ..manifest import Clip
from ..relabel.rules import card_tones

TWIN, DISAGREES, UNSURE, NOT_GRADED, AGREES = "twin", "disagrees", "unsure", "not_graded", "agrees"
GROUPS = (TWIN, DISAGREES, UNSURE, NOT_GRADED, AGREES)  # page order
GROUP_NAMES = {
    TWIN: "scorer hears the twin card's reading",
    DISAGREES: "scorer disagrees",
    UNSURE: "scorer unsure",
    NOT_GRADED: "not graded",
    AGREES: "scorer agrees",
}
DOUBTFUL = 0.5


@dataclass(frozen=True)
class SyllableView:
    heard: str | None
    p_correct: float | None
    note: str | None  # how it was measured, when that matters: "no pitch (creak)", ...
    doubt: float | None  # None: no evidence


@dataclass(frozen=True)
class ScorerView:
    group: str
    doubt: float | None  # the largest syllable doubt; 1.0 for an unscored clip
    overall: float | None
    syllables: list[SyllableView]  # empty when not graded


def _missed(s: SyllableResult) -> bool:
    return s.measured == "NotMeasured" or s.syllable().fallback


def _note(s: SyllableResult) -> str | None:
    if _missed(s):
        return "not measured"
    if s.syllable().unpitched:
        return "no pitch (creak)"
    if "CreakyTail" in s.issues:
        return "creaky tail"
    if "TooShort" in s.issues:
        return "short"
    return None


def _syllable(s: SyllableResult, card_tone: str, intended_tone: str) -> SyllableView:
    if _missed(s):
        return SyllableView(None, None, _note(s), None)
    doubt = 1.0 - s.p_correct if card_tone == intended_tone else s.p_correct
    return SyllableView(s.heard, s.p_correct, _note(s), doubt)


def _leans_to_twin(v: SyllableView, asked: str, twin: str, intended: str) -> bool:
    """On a syllable where the card and its twin differ: the scorer heard the twin's tone, or (the
    twin's tone being the intended one, as on an error card) gives it at least even odds."""
    if asked == twin:
        return False
    if v.heard is not None:
        return v.heard == twin
    return twin == intended and v.p_correct is not None and v.p_correct >= DOUBTFUL


def _group(views: list[SyllableView], asked: list[str], twin: list[str] | None, intended: list[str],
           result: ClipResult, doubt: float | None) -> str:  # fmt: skip
    if twin is not None and any(map(_leans_to_twin, views, asked, twin, intended)):
        return TWIN
    if any(v.heard is not None and v.heard != a for v, a in zip(views, asked, strict=True)):
        return DISAGREES
    if result.overall is None or any(v.doubt is None for v in views) or (doubt or 0.0) >= DOUBTFUL:
        return UNSURE
    return AGREES


def scorer_view(original: Clip, result: ClipResult | None, twin_tones: list[str] | None = None) -> ScorerView:
    """How the scorer's results for a clip compare with what its card (`original`, the row intake
    wrote) asks to be said; `twin_tones` are what its pair twin's card asks, in a pair set."""
    n = len(original.intended.tones)
    if result is None or len(result.syllables) != n:
        return ScorerView(NOT_GRADED, None, None, [])
    asked = card_tones(original)
    views = [
        _syllable(s, tone, intended)
        for s, tone, intended in zip(result.syllables, asked, original.intended.tones, strict=True)
    ]
    doubts = [v.doubt for v in views if v.doubt is not None]
    doubt = 1.0 if result.overall is None else max(doubts, default=None)
    twin = twin_tones if twin_tones is not None and len(twin_tones) == n else None
    group = _group(views, asked, twin, list(original.intended.tones), result, doubt)
    return ScorerView(group, doubt, result.overall, views)
