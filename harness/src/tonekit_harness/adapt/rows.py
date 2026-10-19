"""One `sentence` manifest row (R121) per kept utterance of a public corpus (docs/s05/contracts.md
section 4): the transcript's produced tones are the intended reading, with the toneless
syllables as its labels."""

from __future__ import annotations

from ..manifest import Candidate, Clip, Condition
from . import layout
from .reading import Reading


def sentence_row(utterance: str, speaker: str, reading: Reading, *, source: str, condition: Condition) -> Clip:
    tones = list(reading.tones)
    return Clip(
        id=utterance,
        path=layout.audio_relpath(speaker, utterance),
        speaker=speaker,
        set="sentence",
        label="correct",
        intended=Candidate(id=utterance, tones=tones, labels=list(reading.bases)),
        distractors=[],
        produced_tones=tones,
        condition=condition,
        source=source,
        context="phrase",
    )
