"""The one rule for a path a data file names relative to itself (a gate input's `file`, a corpus
manifest): it stays inside the directory it is relative to."""

from __future__ import annotations

from pathlib import PurePosixPath


def is_relative_inside(path: str) -> bool:
    """True for a non-empty relative path that names something below its base: not absolute, not
    `.`, and no `..` part."""
    parts = PurePosixPath(path).parts
    return bool(path) and bool(parts) and not PurePosixPath(path).is_absolute() and ".." not in parts
