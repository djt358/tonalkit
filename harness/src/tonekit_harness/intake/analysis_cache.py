"""Purge and `tkh eval`'s analysis cache. An entry holds a clip's analysis (its pitch track among
it) under a hash of the WAV bytes, the register it was analysed with and the tonekit build, so one
session's entries cannot be picked out of the rest: purge clears the whole cache, which costs only
the time to recompute it."""

from __future__ import annotations

from pathlib import Path


def clear_analysis_cache(cache_dir: Path) -> int:
    """Remove every entry (and any half-written one) of the cache; returns how many files went."""
    if not cache_dir.is_dir():
        return 0
    removed = 0
    for p in cache_dir.iterdir():
        if p.is_file() and (p.suffix == ".json" or p.name.endswith(".tmp")):
            p.unlink()
            removed += 1
    return removed
