"""Stale markers: a record that what was computed from a corpus (the scoreboard, a calibration fitted
on it) no longer matches it, because something was removed (a purge) or changed.

A marker is `<data root>/stale/<corpus id>.json`. It is written by whatever invalidated the
corpus (`mark_stale`, which P5's purge calls) and removed by the next successful run that
recomputes from it (`clear_stale`, which the scoreboard calls). Marking twice keeps both reasons.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import AwareDatetime, Field, ValidationError

from ..atomic import write_text_atomic
from ..contracts.base import StrictModel, format_validation_error
from ..contracts.registry import RegistryError
from .errors import reason
from .layout import existing_corpus_dir


class StaleReason(StrictModel):
    reason: str = Field(min_length=1)
    marked_at: AwareDatetime


class StaleMarker(StrictModel):
    corpus: str
    reasons: list[StaleReason] = Field(min_length=1)  # oldest first


def stale_dir(root: Path) -> Path:
    return root / "stale"


def stale_path(root: Path, corpus_id: str) -> Path:
    return stale_dir(root) / f"{corpus_id}.json"


def mark_stale(root: Path, corpus_id: str, reason: str, *, now: datetime | None = None) -> StaleMarker:
    """Record that `corpus_id`'s outputs are stale, and why. The corpus must exist under `root`.
    A marker that is already there keeps its reasons (a damaged one is replaced, and the new
    marker says so). Returns the marker as written."""
    if not reason.strip():
        raise ValueError("a stale marker needs a reason")
    existing_corpus_dir(root, corpus_id)  # a mistyped id must not silently mark nothing
    at = now or datetime.now(UTC)
    try:
        earlier = read_marker(root, corpus_id)
        before = earlier.reasons if earlier else []
    except RegistryError:  # marking must work even when the last marker is damaged: say so, replace it
        before = [StaleReason(reason="an earlier stale marker could not be read and was replaced", marked_at=at)]
    marker = StaleMarker(corpus=corpus_id, reasons=[*before, StaleReason(reason=reason.strip(), marked_at=at)])
    write_text_atomic(stale_path(root, corpus_id), marker.model_dump_json(indent=2) + "\n")
    return marker


def read_marker(root: Path, corpus_id: str) -> StaleMarker | None:
    """The marker of `corpus_id`, or None if it is not stale. A marker that cannot be read is an
    error, never "not stale"."""
    path = stale_path(root, corpus_id)
    if not path.exists():
        return None
    try:
        return StaleMarker.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError) as e:
        raise RegistryError(f"{path}: cannot read the stale marker: {reason(e)}") from e
    except json.JSONDecodeError as e:
        raise RegistryError(f"{path}: invalid JSON: {e}") from e
    except ValidationError as e:
        raise RegistryError(f"{path}: {format_validation_error(e)}") from e


def is_stale(root: Path, corpus_id: str) -> bool:
    return read_marker(root, corpus_id) is not None


def clear_stale(root: Path, corpus_id: str) -> bool:
    """Remove the marker (the outputs were recomputed). Returns whether there was one."""
    try:
        stale_path(root, corpus_id).unlink()
    except FileNotFoundError:
        return False
    return True


def stale_corpus_ids(root: Path) -> list[str]:
    """Every corpus with a marker, sorted."""
    if not stale_dir(root).is_dir():
        return []
    return sorted(p.stem for p in stale_dir(root).glob("*.json"))
