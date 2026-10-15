"""Stale markers (`contracts.registry.StaleMarker` at `stale/<corpus id>.json`): what was computed
from a corpus (the scoreboard, a calibration fitted on it) no longer matches it, because something
was removed (a purge) or changed (a relabel).

Whatever invalidated a corpus marks it (`mark_stale`; purge and relabel call it); the next run that
recomputes from it clears the reasons marked before that run began (`clear_stale(marked_before=)`),
so a purge that lands while the run is going keeps the corpus stale. Marking twice keeps both
reasons; a marker that cannot be read is an error to read (never "not stale"), and marking over it
replaces it with one that says so.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from ..atomic import write_text_atomic
from ..contracts.base import format_validation_error
from ..contracts.registry import RegistryError, StaleMarker, StaleReason, stale_path
from .errors import reason as os_reason
from .layout import existing_corpus_dir

UNREADABLE = "an earlier stale marker could not be read and was replaced"


def mark_stale(root: Path, corpus_id: str, reason: str, *, now: datetime | None = None) -> Path:
    """Add `reason` (marked at `now`, default the current time) to the marker of `corpus_id`,
    which must be a corpus under `root`. Returns the marker's path."""
    mark(root, corpus_id, reason, now=now)
    return stale_path(root, corpus_id)


def mark(root: Path, corpus_id: str, reason: str, *, now: datetime | None = None) -> StaleMarker:
    """`mark_stale`, returning the marker as written."""
    if not reason.strip():
        raise ValueError("a stale marker needs a reason")
    existing_corpus_dir(root, corpus_id)  # a mistyped id must not silently mark nothing
    return _add(root, corpus_id, [StaleReason(reason=reason.strip(), marked_at=now or datetime.now(UTC))])


def read_marker(root: Path, corpus_id: str) -> StaleMarker | None:
    """The marker of `corpus_id`, or None if it is not stale. Raises `RegistryError` for a marker
    that cannot be read."""
    path = stale_path(root, corpus_id)
    return _read(path) if path.exists() else None


def is_stale(root: Path, corpus_id: str) -> bool:
    return read_marker(root, corpus_id) is not None


def clear_stale(root: Path, corpus_id: str, *, marked_before: datetime) -> StaleMarker | None:
    """Remove the reasons marked before `marked_before` (when the run that recomputed from the
    corpus began) and return the marker that is left: None when the corpus is no longer stale.

    The marker is first taken out of the way by an atomic rename, so a reason marked from then on
    goes to a new marker, which the reasons kept here are added to. A marker that cannot be read
    counts as marked when it was last written."""
    path = stale_path(root, corpus_id)
    claimed = path.with_name(f".{path.name}.clearing-{os.getpid()}")
    try:
        os.replace(path, claimed)
    except FileNotFoundError:
        return read_marker(root, corpus_id)
    try:
        reasons = _read(claimed).reasons
    except RegistryError:
        written = datetime.fromtimestamp(claimed.stat().st_mtime, UTC)
        reasons = [StaleReason(reason=UNREADABLE, marked_at=written)]
    kept = [r for r in reasons if r.marked_at >= marked_before]
    if kept:
        _add(root, corpus_id, kept)
    claimed.unlink()
    return read_marker(root, corpus_id)


def stale_corpus_ids(root: Path) -> list[str]:
    """Every corpus with a marker, sorted."""
    directory = stale_path(root, "_").parent
    return sorted(p.stem for p in directory.glob("*.json")) if directory.is_dir() else []


def _add(root: Path, corpus_id: str, reasons: list[StaleReason]) -> StaleMarker:
    """Write the marker with `reasons` added to those already there (oldest first, each once); a
    damaged marker is replaced by one that says so."""
    path = stale_path(root, corpus_id)
    earlier: list[StaleReason] = []
    if path.exists():
        try:
            earlier = _read(path).reasons
        except RegistryError:
            earlier = [StaleReason(reason=UNREADABLE, marked_at=min(r.marked_at for r in reasons))]
    merged = sorted(_unique([*earlier, *reasons]), key=lambda r: r.marked_at)
    marker = StaleMarker(corpus=corpus_id, reasons=merged)
    write_text_atomic(path, marker.model_dump_json(indent=2) + "\n")
    return marker


def _unique(reasons: list[StaleReason]) -> list[StaleReason]:
    seen: set[tuple[str, datetime]] = set()
    out = []
    for r in reasons:
        if (r.reason, r.marked_at) not in seen:
            seen.add((r.reason, r.marked_at))
            out.append(r)
    return out


def _read(path: Path) -> StaleMarker:
    try:
        return StaleMarker.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError) as e:
        raise RegistryError(f"{path}: cannot read the stale marker: {os_reason(e)}") from e
    except json.JSONDecodeError as e:
        raise RegistryError(f"{path}: invalid JSON: {e}") from e
    except ValidationError as e:
        raise RegistryError(f"{path}: {format_validation_error(e)}") from e
