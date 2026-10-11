"""`tkh eval --results PATH`: how tonekit graded each clip, as JSON (`tonekit.eval-results.v1`).

The report is the human-readable view; this file is for tools that need the scorer's view clip by
clip and syllable by syllable, such as `tkh review` (heard tone and p_correct per syllable). It
lists clips by id (`<CODE>-<card>` for volunteers), so like the report it is written under the data
root, and purge removes it with the reports that mention the session. No timestamps: the output
depends only on the results."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import Field, ValidationError

from .atomic import write_text_atomic
from .contracts.base import StrictModel, format_validation_error

if TYPE_CHECKING:  # evaluate imports this module to write the file
    from .evaluate import Result, Syllable

SCHEMA = "tonekit.eval-results.v1"


class ResultsError(ValueError):
    """A results file could not be read; the message starts with its path."""


class SyllableResult(StrictModel):
    expected: str  # the intended reading's tone
    heard: str | None  # tonekit's best tone for the syllable; None: not measured
    p_correct: float
    distance: float | None
    measured: str  # "Full", "Partial" or "NotMeasured"
    issues: list[str] = []  # tonekit `MeasureIssue` names

    def syllable(self) -> Syllable:
        """As `evaluate.Syllable`, whose properties (`fallback`, `unpitched`) say how to read it."""
        from .evaluate import Syllable

        return Syllable(
            expected=self.expected,
            heard=self.heard,
            p_correct=self.p_correct,
            distance=self.distance,
            measured=self.measured,
            issues=list(self.issues),
        )


class ClipResult(StrictModel):
    id: str
    set: str
    pair: str | None
    label: str
    speaker: str
    overall: float | None  # None: not scored
    intended_rank: int
    margin_llr: float | None  # None when it is not finite
    register_source: str
    issues: list[str] = []  # the analysis's signal issues
    syllables: list[SyllableResult]


class EvalResults(StrictModel):
    schema_: Literal["tonekit.eval-results.v1"] = Field(alias="schema")
    register_from: str  # where each clip's register came from (`evaluate.REGISTER_FROM`)
    tonekit_py: str  # the build that graded (`evaluate.tonekit_py_fingerprint`)
    clips: list[ClipResult]


def _finite(x: float | None) -> float | None:
    return x if x is not None and math.isfinite(x) else None


def _clip(r: Result) -> ClipResult:
    return ClipResult(
        id=r.id,
        set=r.set,
        pair=r.pair,
        label=r.label,
        speaker=r.speaker,
        overall=r.overall,
        intended_rank=r.intended_rank,
        margin_llr=_finite(r.margin_llr),
        register_source=r.register_source,
        issues=list(r.issues),
        syllables=[
            SyllableResult(
                expected=s.expected,
                heard=s.heard,
                p_correct=s.p_correct,
                distance=_finite(s.distance),
                measured=s.measured,
                issues=list(s.issues),
            )
            for s in r.syllables
        ],
    )


def results_document(results: Sequence[Result], *, register_from: str, tonekit_py: str) -> EvalResults:
    return EvalResults(
        schema=SCHEMA, register_from=register_from, tonekit_py=tonekit_py, clips=[_clip(r) for r in results]
    )


def write_results(path: str | Path, document: EvalResults) -> None:
    """Write `document` to `path` (parent directories are created; atomic)."""
    write_text_atomic(Path(path), document.model_dump_json(by_alias=True, indent=1) + "\n")


def load_results(path: str | Path) -> EvalResults:
    """Read a results file; raises `ResultsError` naming the path."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ResultsError(f"{path}: cannot read it: {e}") from e
    try:
        return EvalResults.model_validate_json(text)
    except ValidationError as e:
        raise ResultsError(f"{path}: not a {SCHEMA} file:\n{format_validation_error(e)}") from e
