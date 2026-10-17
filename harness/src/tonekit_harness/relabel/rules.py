"""One clip's row after a listener's decision, from the row intake wrote for it (the card's
reading). Pure: no files.

- as the card says: the row as intake wrote it;
- heard other tones: `produced_tones` are the tones heard; the label is `correct` when they are the
  intended reading (an error card read as the correct word) and `tone_error` when they are not (a
  correct card read with a wrong tone, or an error card read with another error); a label other
  than those two is kept (ruling R112);
- unclear: the row as intake wrote it, flagged `needs_listen` for another listen (R112);
- exclude (bad audio): no row. The audio stays until purge.

A public corpus's sentence (R121) has no card: its reading is what its transcript says was said,
so tones heard otherwise become both its intended reading and its produced tones, and it stays
`correct`.

Whether a pair is still a pair is `pairs`' business."""

from __future__ import annotations

from ..contracts.relabel import AppliedDecision, Decision
from ..manifest import SENTENCE, Clip

GRADED_LABELS = frozenset({"correct", "tone_error"})


def card_tones(original: Clip) -> list[str]:
    """What the card asks to be said: the row's `produced_tones` as intake wrote them (a row from
    elsewhere may have none: then its intended reading)."""
    return list(original.produced_tones or original.intended.tones)


def _label(original: Clip, tones: list[str]) -> str:
    if original.label not in GRADED_LABELS:
        return original.label
    return "correct" if tones == list(original.intended.tones) else "tone_error"


def relabelled(original: Clip, decision: Decision | AppliedDecision | None) -> Clip | None:
    """The row of a clip whose card reading is `original` once `decision` applies (None: no
    decision, the original row). None when the clip is excluded."""
    if decision is None or decision.verdict == "as_card":
        return original
    if decision.verdict == "exclude":
        return None
    if decision.verdict == "unclear":
        return original.model_copy(update={"needs_listen": True})
    tones = list(decision.tones or [])
    if tones == card_tones(original):
        return original
    if original.set == SENTENCE:
        intended = original.intended.model_copy(update={"tones": tones})
        return original.model_copy(update={"produced_tones": tones, "intended": intended})
    return original.model_copy(update={"produced_tones": tones, "label": _label(original, tones)})
