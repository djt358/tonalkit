"""Per-syllable observations for fitting: a forced decode of the reading each clip's speaker was
asked to produce, on the tonekit build and pack being fitted."""

from __future__ import annotations

import json
from dataclasses import dataclass

import tonekit_py

from ..evaluate import Grader, grading_target
from ..manifest import Clip

# How a syllable of the produced reading was measured.
SHAPE, UNPITCHED, MISSED = "shape", "unpitched", "missed"


@dataclass(frozen=True)
class Observation:
    """One syllable of a clip's produced reading."""

    clip: str
    speaker: str
    tone: str  # the tone the card asked for (`produced_tones`, else the intended reading's)
    index: int
    count: int
    prev: str | None  # the previous syllable's produced tone
    final: bool  # the phrase's last syllable
    kind: str  # SHAPE, UNPITCHED or MISSED
    shape: dict | None  # the ToneShape JSON when `kind` is SHAPE and it sits on a nucleus

    @property
    def context(self) -> tuple[str | None, bool]:
        return self.prev, self.final


def produced(clip: Clip) -> list[str]:
    """The tones the clip's speaker was asked to produce."""
    return list(clip.produced_tones or clip.intended.tones)


def _candidate(clip: Clip, tones: list[str]) -> dict:
    return {
        "id": f"{clip.id}/produced",
        "targets": [{"tone": t, "lexical_variants": [], "label": None} for t in tones],
    }


def _kind(measured: str | dict) -> str:
    if isinstance(measured, str):
        return SHAPE
    (key, value), = measured.items()
    issues = value.get("issues", []) if key == "Partial" else [value.get("issue")]
    if "Unpitched" in issues:
        return UNPITCHED
    if key == "NotMeasured" or "NoNucleus" in issues:
        return MISSED
    return SHAPE


def observe_clip(clip: Clip, grader: Grader, register_json: str | None) -> list[Observation]:
    """The observations of one clip: its produced reading decoded alone, each syllable's shape
    taken from the lattice's TBU at the same span (a syllable on an extra candidate of the count
    stage has none in the lattice and is left without a shape)."""
    analysis = grader.analysis(clip, register_json)
    tones = produced(clip)
    grading = json.dumps(grading_target(grader.accent))
    decoded = json.loads(
        tonekit_py.decode(
            analysis, grader.pack_toml, grader.calib_json, grading, json.dumps([_candidate(clip, tones)])
        )
    )
    lattice = json.loads(tonekit_py.lattice(analysis, grader.pack_toml, grader.calib_json, grading))
    shapes = {(t["span"]["start_frame"], t["span"]["end_frame"]): t["shape"] for t in lattice["tbus"]}
    out = []
    for k, fit in enumerate(decoded["candidates"][0]["syllables"]):
        kind = _kind(fit["judgement"]["measured"])
        span = (fit["span"]["start_frame"], fit["span"]["end_frame"])
        out.append(
            Observation(
                clip=clip.id,
                speaker=clip.speaker,
                tone=tones[k],
                index=k,
                count=len(tones),
                prev=tones[k - 1] if k else None,
                final=k + 1 == len(tones),
                kind=kind,
                shape=shapes.get(span) if kind == SHAPE else None,
            )
        )
    return out
