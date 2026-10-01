"""The promises of the data root, kept by mechanism: what a selection may not be used for.

- Fitting (calibration, anything that learns parameters) never sees a `gate` or `heldout` speaker,
  and only clips whose source the data register clears (`allow`).
- A gate is measured on real recordings: never on a synthetic corpus or synthetic clip, and only on
  sources the register clears.

"Synthetic" and "cleared" are `clearance`'s (`is_synthetic`, `is_allowed`). Each refusal names the
corpus and speaker at fault and says why, every problem at once.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping

from .. import clearance
from .items import CorpusClip

NEVER_FITTED = frozenset({"gate", "heldout"})
MAX_PROBLEMS_SHOWN = 10


class RefusalError(ValueError):
    """The selection may not be used for this: the message lists why."""


def check_fitting(items: Iterable[CorpusClip], register: Mapping[str, str]) -> None:
    """Raise `RefusalError` unless nothing in `items` is a gate or heldout speaker's, and every
    clip's source is cleared in `register`."""
    items = list(items)
    problems = _split_problems(items) + _source_problems(items, register)
    _raise_if(problems, "refusing to fit parameters on this selection")


def check_gate(items: Iterable[CorpusClip], register: Mapping[str, str]) -> None:
    """Raise `RefusalError` if any of `items` is synthetic or its source is not cleared in
    `register`."""
    items = list(items)
    synthetic = _synthetic_problems(items)
    real = [i for i in items if i.corpus.kind != "synthetic" and not clearance.is_synthetic(i.clip)]
    _raise_if(synthetic + _source_problems(real, register), "refusing to grade a gate on this selection")


def _raise_if(problems: list[str], headline: str) -> None:
    if not problems:
        return
    shown = problems[:MAX_PROBLEMS_SHOWN]
    if len(problems) > MAX_PROBLEMS_SHOWN:
        shown.append(f"and {len(problems) - MAX_PROBLEMS_SHOWN} more")
    raise RefusalError(headline + ":\n" + "\n".join(f"  {p}" for p in shown))


def _split_problems(items: list[CorpusClip]) -> list[str]:
    clips = Counter((i.qualified_speaker, i.speaker.split) for i in items if i.speaker.split in NEVER_FITTED)
    return [
        f"{who}: speaker is in split {split!r} ({_clips(n)}); a fit never sees gate or heldout speakers"
        for (who, split), n in clips.items()
    ]


def _synthetic_problems(items: list[CorpusClip]) -> list[str]:
    problems = []
    for corpus_id in dict.fromkeys(i.corpus.id for i in items):
        mine = [i for i in items if i.corpus.id == corpus_id]
        if mine[0].corpus.kind == "synthetic":
            problems.append(f"{corpus_id}: synthetic corpus ({_clips(len(mine))}); a gate is measured on real recordings")
            continue
        n = sum(clearance.is_synthetic(i.clip) for i in mine)
        if n:
            who = ", ".join(sorted({i.qualified_speaker for i in mine if clearance.is_synthetic(i.clip)}))
            problems.append(f"{corpus_id}: synthetic clips ({_clips(n)}, speakers {who}); a gate is measured on real recordings")
    return problems


def _source_problems(items: list[CorpusClip], register: Mapping[str, str]) -> list[str]:
    uncleared = Counter((i.corpus.id, i.clip.source) for i in items if not clearance.is_allowed(i.clip, register))
    return [f"{corpus_id}: source {source!r} {_status(source, register)} ({_clips(n)})" for (corpus_id, source), n in uncleared.items()]


def _status(source: str, register: Mapping[str, str]) -> str:
    if source not in register:
        return "is not in the data register"
    return f"is {register[source]!r} in the data register, not 'allow'"


def _clips(n: int) -> str:
    return f"{n} clip" + ("" if n == 1 else "s")

