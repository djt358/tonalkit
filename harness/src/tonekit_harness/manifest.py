"""Corpus manifest: one JSON object per line, validated into `Clip` rows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

ClipSet = Literal["gate", "diag_t23", "diag_count", "diag_minimal", "quiet", "register", "synthetic"]
ClipLabel = Literal["correct", "tone_error", "graded", "n/a"]


class ManifestError(ValueError):
    """A manifest could not be read; the message starts with `<path>:<line>:`."""


class _Model(BaseModel):
    # Unknown keys are errors: a typo such as "distractor" must not silently drop data.
    model_config = ConfigDict(extra="forbid")


class Candidate(_Model):
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


class Condition(_Model):
    noise: str
    distance: str


class Clip(_Model):
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


def load(path: str | Path) -> list[Clip]:
    """Read a JSONL manifest. Blank lines are skipped; a bad row raises `ManifestError` naming its line."""
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
                clips.append(Clip.model_validate(obj))
            except ValidationError as e:
                raise ManifestError(f"{where}: {e}") from e
    return clips


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
