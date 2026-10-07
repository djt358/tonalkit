"""What a listener heard each clip say (contracts.md section 7): the file `tkh review`'s page exports
(`relabels-<corpus>.json`), and the log `tkh relabel` keeps of what applying it changed
(`corpora/<corpus>/relabels.jsonl`). Both name clips by id (`<CODE>-<card>`), so both stay under
the data root, and purge removes a session's entries from the log."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, StringConstraints, ValidationError, model_validator

from ..manifest import Clip
from .base import StrictModel, format_validation_error

EXPORT_SCHEMA = "tonekit.relabels.v1"

# as_card: said as the card asks; heard: said with the tones given (one per syllable);
# unclear: the listener cannot tell; exclude: bad audio, the clip leaves the manifest.
Verdict = Literal["as_card", "heard", "unclear", "exclude"]
WITH_TONES: frozenset[str] = frozenset({"as_card", "heard"})

_Who = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class RelabelError(ValueError):
    """A relabel file or log could not be read or applied; nothing was written."""


class Decision(StrictModel):
    """One clip's verdict, as the page exports it."""

    clip: str = Field(min_length=1)
    verdict: Verdict
    tones: list[str] | None = None  # as_card and heard: the tones heard; unclear and exclude: none
    decided_at: AwareDatetime

    @model_validator(mode="after")
    def _tones_fit_the_verdict(self) -> Decision:
        if self.verdict == "heard" and not self.tones:
            raise ValueError(f"clip {self.clip!r}: verdict 'heard' needs the tones heard")
        if self.verdict not in WITH_TONES and self.tones is not None:
            raise ValueError(f"clip {self.clip!r}: verdict {self.verdict!r} takes no tones")
        return self


class RelabelExport(StrictModel):
    """`relabels-<corpus>.json`, downloaded from the review page."""

    schema_: Literal["tonekit.relabels.v1"] = Field(alias="schema")
    corpus: str = Field(min_length=1)
    who: _Who  # the listener's initials, typed on the page
    exported_at: AwareDatetime
    decisions: list[Decision]

    @model_validator(mode="after")
    def _one_decision_per_clip(self) -> RelabelExport:
        twice = [c for c, n in Counter(d.clip for d in self.decisions).items() if n > 1]
        if twice:
            raise ValueError(f"clips decided more than once: {', '.join(twice)}")
        return self


class AppliedDecision(StrictModel):
    """A decision as the log keeps it: with who made it."""

    verdict: Verdict
    tones: list[str] | None = None
    decided_at: AwareDatetime
    who: _Who

    def same_verdict(self, other: Decision | AppliedDecision) -> bool:
        return (self.verdict, self.tones) == (other.verdict, other.tones)


class RowChange(StrictModel):
    before: Clip | None  # None: the row was not in the manifest (excluded before)
    after: Clip | None  # None: the row left the manifest (excluded)


class LogEntry(StrictModel):
    """One line of `relabels.jsonl`: a clip's new decision, the change to its row, or both. A row
    can change without a decision of its own when its pair twin's relabel breaks the pair."""

    session: str | None  # the session code of a volunteer clip; purge removes its entries by it
    clip: str
    applied_at: AwareDatetime
    decision: AppliedDecision | None = None
    row: RowChange | None = None

    @model_validator(mode="after")
    def _says_something(self) -> LogEntry:
        if self.decision is None and self.row is None:
            raise ValueError(f"clip {self.clip!r}: an entry needs a decision or a row change")
        return self


def parse_export(text: str, source: str) -> RelabelExport:
    try:
        return RelabelExport.model_validate_json(text)
    except ValidationError as e:
        raise RelabelError(f"{source}: not a {EXPORT_SCHEMA} file:\n{format_validation_error(e)}") from e


def load_export(path: str | Path) -> RelabelExport:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise RelabelError(f"{path}: cannot read it: {e}") from e
    return parse_export(text, str(path))


def load_log(path: str | Path) -> list[LogEntry]:
    """The entries of a relabel log, oldest first; no file means no entries."""
    path = Path(path)
    if not path.exists():
        return []
    entries = []
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                entries.append(LogEntry.model_validate(json.loads(line)))
            except json.JSONDecodeError as e:
                raise RelabelError(f"{path}:{lineno}: invalid JSON: {e}") from e
            except ValidationError as e:
                raise RelabelError(f"{path}:{lineno}: {format_validation_error(e)}") from e
    return entries
