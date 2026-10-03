"""Corpus manifest: one JSON object per line, validated into `Clip` rows."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, get_args

from pydantic import Field, ValidationError, model_validator

from .contracts.base import StrictModel

# The deck's vocabulary (contracts.md section 1); a clip may also be synthetic, or `graded`.
CardSet = Literal["gate", "diag_t23", "diag_count", "diag_minimal", "diag_context", "quiet", "register"]
CardLabel = Literal["correct", "tone_error", "n/a"]
Context = Literal["phrase", "isolated"]  # phrase: sandhi applies; isolated: the citation reading
ClipSet = Literal[*get_args(CardSet), "synthetic"]
ClipLabel = Literal[*get_args(CardLabel), "graded"]


class ManifestError(ValueError):
    """A manifest could not be read; the message starts with `<path>:<line>:`."""


class Candidate(StrictModel):
    id: str
    tones: list[str]
    # May be shorter than `tones`; missing entries mean "no label".
    labels: list[str]

    @model_validator(mode="after")
    def _labels_fit_tones(self) -> Candidate:
        if len(self.labels) > len(self.tones):
            raise ValueError(
                f"candidate {self.id!r} has {len(self.labels)} labels for {len(self.tones)} tones"
            )
        return self


class Condition(StrictModel):
    noise: str
    distance: str


class Clip(StrictModel):
    id: str
    path: str
    speaker: str
    set: ClipSet
    pair: str | None = None
    label: ClipLabel
    intended: Candidate
    distractors: list[Candidate] = []
    produced_tones: list[str] | None = None
    condition: Condition
    source: str  # a data-register.csv id
    synthetic: dict | None = None
    needs_listen: bool = False
    # Set for clips recorded from a deck (contracts.md section 4).
    card: str | None = None  # deck card id
    deck: str | None = None  # deck id
    take: int | None = Field(default=None, ge=1)  # takes recorded for the kept clip
    context: Context | None = None

    @model_validator(mode="after")
    def _synthetic_iff_synthetic_set(self) -> Clip:
        if self.set == "synthetic" and self.synthetic is None:
            raise ValueError(f"clip {self.id!r} is in set 'synthetic' but has no `synthetic` field")
        if self.set != "synthetic" and self.synthetic is not None:
            raise ValueError(
                f"clip {self.id!r} has a `synthetic` field but is in set {self.set!r}; "
                "synthetic clips belong in set 'synthetic'"
            )
        return self


def load(path: str | Path, *, register: Mapping[str, str] | None = None) -> list[Clip]:
    """Read a JSONL manifest. Blank lines are skipped; a bad row raises `ManifestError` naming its
    line. With a `register` (data-register.csv's ids, see `provenance.load_register`), a `source`
    that is not one of them is a bad row too."""
    path = Path(path)
    clips: list[Clip] = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            where = f"{path}:{lineno}"
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ManifestError(f"{where}: invalid JSON: {e}") from e
            if not isinstance(obj, dict):
                raise ManifestError(f"{where}: expected a JSON object, got {type(obj).__name__}")
            try:
                clip = Clip.model_validate(obj)
            except ValidationError as e:
                raise ManifestError(f"{where}: {e}") from e
            if register is not None and clip.source not in register:
                raise ManifestError(
                    f"{where}: clip {clip.id!r}: source {clip.source!r} is not an id in the data register"
                )
            clips.append(clip)
    return clips


def write(path: str | Path, clips: list[Clip]) -> None:
    """Write `clips` as a JSONL manifest that `load` reads back; the directory is created."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(c.model_dump_json() + "\n" for c in clips), encoding="utf-8")


def to_candidate_json(c: Candidate) -> str:
    """The tonekit candidate JSON for `c`; missing or empty labels become null."""
    targets = [
        {
            "tone": tone,
            "lexical_variants": [],
            "label": (c.labels[i] or None) if i < len(c.labels) else None,
        }
        for i, tone in enumerate(c.tones)
    ]
    return json.dumps({"id": c.id, "targets": targets}, ensure_ascii=False)
