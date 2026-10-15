"""The promises of the data root, kept by mechanism: what a selection may not be used for.

- Fitting (calibration, anything that learns parameters) never sees a `gate` or `heldout` speaker,
  and only clips whose source the data register clears (`allow`).
- A gate is measured on real recordings: never on a synthetic corpus or synthetic clip, and only on
  sources the register clears.
- Nothing is fitted or graded on an empty selection: a typo must not pass vacuously.

"Synthetic" and "cleared" are `clearance`'s (`is_synthetic`, `is_allowed`). Each refusal names the
corpus and speaker at fault and says why, every problem at once.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .. import clearance
from .errors import cut
from .items import CorpusClip

NEVER_FITTED = frozenset({"gate", "heldout"})
GATE_NEEDS_REAL = "a gate is measured on real recordings"
FITTING = "refusing to fit parameters on this selection"
GATE = "refusing to grade a gate on this selection"
EMPTY = "the selection is empty: no clip matches the corpora, splits and sets asked for"


@dataclass(frozen=True)
class Refusal:
    """Why a selection may not be used: `problems` (one line each), how many clips are at fault,
    and whether every one of them is synthetic (a smoke run grades those, without a verdict)."""

    headline: str
    problems: tuple[str, ...]
    clips: int = 0
    synthetic_only: bool = False

    def message(self) -> str:
        return self.headline + ":\n" + "\n".join(f"  {p}" for p in cut(list(self.problems)))


class RefusalError(ValueError):
    """The selection may not be used for this: the message lists why; `refusal` holds it."""

    def __init__(self, refusal: Refusal) -> None:
        super().__init__(refusal.message())
        self.refusal = refusal


def fitting_refusal(items: Iterable[CorpusClip], register: Mapping[str, str]) -> Refusal | None:
    """Why nothing may be fitted on `items` (a gate or heldout speaker's clip, a source the register
    does not clear, or no clip at all), or None."""
    items = list(items)
    if not items:
        return Refusal(FITTING, (EMPTY,))
    split = [i for i in items if i.speaker.split in NEVER_FITTED]
    uncleared = [i for i in items if not clearance.is_allowed(i.clip, register)]
    problems = _split_problems(split) + _source_problems(uncleared, register)
    at_fault = {i.key for i in split} | {i.key for i in uncleared}
    return Refusal(FITTING, tuple(problems), len(at_fault)) if problems else None


def gate_refusal(items: Iterable[CorpusClip], register: Mapping[str, str]) -> Refusal | None:
    """Why `items` may not back a gate verdict (a synthetic corpus or clip, a real clip whose
    source the register does not clear, or no clip at all), or None."""
    items = list(items)
    if not items:
        return Refusal(GATE, (EMPTY,))
    synthetic = [i for i in items if _synthetic(i)]
    uncleared = [i for i in items if not _synthetic(i) and not clearance.is_allowed(i.clip, register)]
    problems = _synthetic_problems(synthetic) + _source_problems(uncleared, register)
    if not problems:
        return None
    return Refusal(GATE, tuple(problems), len(synthetic) + len(uncleared), synthetic_only=not uncleared)


def check_fitting(items: Iterable[CorpusClip], register: Mapping[str, str]) -> None:
    """Raise `RefusalError` if `fitting_refusal` finds a reason."""
    if (refusal := fitting_refusal(items, register)) is not None:
        raise RefusalError(refusal)


def check_gate(items: Iterable[CorpusClip], register: Mapping[str, str]) -> None:
    """Raise `RefusalError` if `gate_refusal` finds a reason."""
    if (refusal := gate_refusal(items, register)) is not None:
        raise RefusalError(refusal)


def _synthetic(i: CorpusClip) -> bool:
    return i.corpus.kind == "synthetic" or clearance.is_synthetic(i.clip)


def _split_problems(items: list[CorpusClip]) -> list[str]:
    clips = Counter((i.qualified_speaker, i.speaker.split) for i in items)
    return [
        f"{who}: speaker is in split {split!r} ({_clips(n)}); a fit never sees gate or heldout speakers"
        for (who, split), n in clips.items()
    ]


def _synthetic_problems(items: list[CorpusClip]) -> list[str]:
    problems = []
    for corpus_id in dict.fromkeys(i.corpus.id for i in items):
        mine = [i for i in items if i.corpus.id == corpus_id]
        if mine[0].corpus.kind == "synthetic":
            problems.append(f"{corpus_id}: synthetic corpus ({_clips(len(mine))}); {GATE_NEEDS_REAL}")
            continue
        who = ", ".join(sorted({i.qualified_speaker for i in mine}))
        problems.append(f"{corpus_id}: synthetic clips ({_clips(len(mine))}, speakers {who}); {GATE_NEEDS_REAL}")
    return problems


def _source_problems(items: list[CorpusClip], register: Mapping[str, str]) -> list[str]:
    uncleared = Counter((i.corpus.id, i.clip.source) for i in items)
    return [
        f"{corpus_id}: source {source!r} {_status(source, register)} ({_clips(n)})"
        for (corpus_id, source), n in uncleared.items()
    ]


def _status(source: str, register: Mapping[str, str]) -> str:
    if source not in register:
        return "is not in the data register"
    return f"is {register[source]!r} in the data register, not 'allow'"


def _clips(n: int) -> str:
    return f"{n} clip" + ("" if n == 1 else "s")
