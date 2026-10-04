"""A stale marker (`stale/<corpus id>.json`, `contracts.registry.StaleMarker`): what was computed
from a corpus no longer matches it. Purge marks the corpora it changed; the next run that
recomputes from a corpus clears its marker (E1, E3)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..atomic import write_text_atomic
from ..contracts.registry import StaleMarker, StaleReason, stale_path

UNREADABLE = "an earlier stale marker could not be read and was replaced"


def mark_stale(root: Path, corpus_id: str, reason: str, *, now: datetime) -> Path:
    """Add `reason` to the corpus's marker (created if there is none; a damaged one is replaced,
    and the new marker says so). Returns the marker's path."""
    path = stale_path(root, corpus_id)
    earlier: list[StaleReason] = []
    if path.exists():
        try:
            earlier = StaleMarker.model_validate_json(path.read_text(encoding="utf-8")).reasons
        except (OSError, ValueError):  # unreadable or invalid: marking must still work
            earlier = [StaleReason(reason=UNREADABLE, marked_at=now)]
    marker = StaleMarker(corpus=corpus_id, reasons=[*earlier, StaleReason(reason=reason, marked_at=now)])
    write_text_atomic(path, marker.model_dump_json(indent=2) + "\n")
    return path
