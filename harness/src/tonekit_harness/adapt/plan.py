"""Which utterances of a public corpus become rows, before any audio is touched: the speakers
`--limit-speakers` keeps, then per utterance its reading (R122) or why it is dropped, and the
`--max-syllables` cap (R123)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..manifest import Clip, Condition
from . import drops, layout
from .corpus_files import Found, Utterance
from .reading import Dropped, read
from .rows import sentence_row


@dataclass(frozen=True)
class Planned:
    utterance: Utterance
    row: Clip


@dataclass
class Plan:
    speakers_in_corpus: int
    speakers: list[str]  # the speakers adapted (all, or the first `--limit-speakers` by id)
    utterances: int  # utterances of those speakers
    kept: list[Planned] = field(default_factory=list)
    dropped: drops.Drops = field(default_factory=drops.Drops)


def chosen_speakers(found: Found, limit: int | None) -> list[str]:
    ids = sorted({u.speaker for u in found.utterances})
    return ids if limit is None else ids[:limit]


def plan(
    found: Found, *, max_syllables: int, limit_speakers: int | None, source: str, condition: Condition
) -> Plan:
    """The rows of `found`'s utterances that are kept, and the tally of the others."""
    speakers = chosen_speakers(found, limit_speakers)
    wanted = set(speakers)
    mine = sorted((u for u in found.utterances if u.speaker in wanted), key=lambda u: u.id)
    out = Plan(speakers_in_corpus=len({u.speaker for u in found.utterances}), speakers=speakers, utterances=len(mine))
    for u in mine:
        why = _problem(u)
        reading = None if why else read(u.transcript)  # type: ignore[arg-type]
        if isinstance(reading, Dropped):
            why = reading.reason
        elif reading is not None and len(reading.tones) > max_syllables:
            why = drops.TOO_LONG
        if why:
            out.dropped.add(why, u.id)
            continue
        row = sentence_row(u.id, u.speaker, reading, source=source, condition=condition)  # type: ignore[arg-type]
        out.kept.append(Planned(u, row))
    return out


def _problem(u: Utterance) -> str | None:
    if not (layout.safe_id(u.id) and layout.safe_id(u.speaker)):
        return drops.MALFORMED
    if u.problem:
        return u.problem
    if u.transcript is None:
        return drops.NO_TRANSCRIPT
    if u.audio is None:
        return drops.NO_AUDIO
    return None
