"""Gate files (`gates/<id>.toml`, contracts.md section 5): what a gate selects, measures and
requires. The metric registry belongs to the gate runner; the loaders take the known names."""

from __future__ import annotations

import difflib
import tomllib
from collections import Counter
from collections.abc import Collection
from pathlib import Path, PurePosixPath
from textwrap import indent
from typing import Annotated, Literal

from pydantic import Field, ValidationError, ValidationInfo, model_validator

from ..manifest import CardSet
from .base import StrictModel, format_validation_error
from .registry import Kind, Split

_ID = r"^[a-z0-9][a-z0-9-]*$"
_Nonempty = Annotated[str, Field(min_length=1)]

ReportBy = Literal["speaker", "background", "grew_up_hearing", "context"]


class GateError(ValueError):
    """A gate file could not be read or breaks a rule; the message starts with its source."""


class GateMeta(StrictModel):
    id: str = Field(pattern=_ID)
    phase: str = Field(min_length=1)
    summary: str = Field(min_length=1)


class Select(StrictModel):
    corpora: list[_Nonempty] = Field(min_length=1)  # corpus ids or globs
    kinds: list[Kind] = Field(min_length=1)
    splits: list[Split] = Field(min_length=1)
    sets: list[CardSet] = Field(min_length=1)

    @model_validator(mode="after")
    def _no_synthetic(self) -> Select:
        if "synthetic" in self.kinds:
            raise ValueError("select.kinds: a gate refuses synthetic corpora")
        return self


class Thresholds(StrictModel):
    method: Literal["loso", "lopo"]  # leave-one-speaker-out; leave-one-pair-out for one speaker


class Criterion(StrictModel):
    metric: str = Field(min_length=1)
    min: float | None = None
    max: float | None = None

    @model_validator(mode="after")
    def _one_bound(self) -> Criterion:
        given = (self.min is not None) + (self.max is not None)
        if given != 1:
            raise ValueError(
                f"criterion {self.metric!r}: needs exactly one of min and max, "
                f"got {'both' if given else 'neither'}"
            )
        return self


class Requires(StrictModel):
    speakers_min: int = Field(default=1, ge=1)
    l1_min: int = Field(default=1, ge=1)


class Report(StrictModel):
    by: list[ReportBy] = []
    diagnostics: list[str] = []  # metric names


class GateInput(StrictModel):
    """A metric measured elsewhere: `file` holds its value and provenance. A missing file makes
    the verdict INCOMPLETE."""

    metric: str = Field(min_length=1)
    file: str
    summary: str = ""

    @model_validator(mode="after")
    def _file_is_relative(self) -> GateInput:
        path = PurePosixPath(self.file)
        if not self.file or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"input {self.metric!r}: file {self.file!r} must be a relative path with no '..'")
        return self


class PathsUnchanged(StrictModel):
    """No diff since `base` (a git ref) in `paths` (git pathspecs: `git diff <base> -- <paths>`;
    ":(exclude)dir" allows changes in dir, so "no diff outside packs/" is [".", ":(exclude)packs"])."""

    id: str = Field(pattern=_ID)
    kind: Literal["paths_unchanged"]
    base: str = Field(min_length=1)
    paths: list[_Nonempty] = Field(min_length=1)
    summary: str = ""


class GateFile(StrictModel):
    gate: GateMeta
    select: Select
    thresholds: Thresholds
    criterion: list[Criterion] = Field(min_length=1)
    requires: Requires = Field(default_factory=Requires)
    report: Report = Field(default_factory=Report)
    input: list[GateInput] = []
    check: list[PathsUnchanged] = []

    @model_validator(mode="after")
    def _names_are_unique_and_known(self, info: ValidationInfo) -> GateFile:
        problems = [
            f"input metric {m!r} appears more than once"
            for m, n in Counter(i.metric for i in self.input).items()
            if n > 1
        ]
        problems += [
            f"check {i!r} appears more than once" for i, n in Counter(c.id for c in self.check).items() if n > 1
        ]
        known = (info.context or {}).get("known_metrics")
        if known is not None:
            valid = sorted(set(known) | {i.metric for i in self.input})
            problems += [_unknown(m, "[[criterion]]", valid) for m in (c.metric for c in self.criterion) if m not in valid]
            problems += [_unknown(m, "[report] diagnostics", valid) for m in self.report.diagnostics if m not in valid]
        if problems:
            raise ValueError("\n".join(problems))
        return self


def _unknown(name: str, where: str, valid: list[str]) -> str:
    close = difflib.get_close_matches(name, valid, n=1)
    hint = f"did you mean {close[0]!r}?" if close else f"known: {', '.join(valid)}"
    return f"unknown metric {name!r} in {where} ({hint})"


def parse_gate(data: dict, *, known_metrics: Collection[str], source: str = "gate") -> GateFile:
    """Validate a gate's data (its TOML as a dict). Every criterion and diagnostic must name a
    metric in `known_metrics` or one an `[[input]]` supplies. Raises `GateError` listing every
    problem. (`GateFile.model_validate` alone checks structure but not metric names.)"""
    try:
        return GateFile.model_validate(data, context={"known_metrics": set(known_metrics)})
    except ValidationError as e:
        problems = format_validation_error(e, data, {"criterion": "metric", "input": "metric", "check": "id"})
        raise GateError(f"{source}: invalid gate\n{indent(problems, '  ')}") from e


def load_gate(path: str | Path, *, known_metrics: Collection[str]) -> GateFile:
    """Read and validate the gate TOML at `path` (see `parse_gate`)."""
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise GateError(f"{path}: invalid TOML: {e}") from e
    return parse_gate(data, known_metrics=known_metrics, source=str(path))
