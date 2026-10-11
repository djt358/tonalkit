"""Purge and `tkh review`'s pages (`review/<corpus>/` under the data root): a page links the corpus's
audio and names every clip by id, so a page that mentions the session goes, whole. `tkh review`
makes it again from what is left."""

from __future__ import annotations

from pathlib import Path

from . import layout


def _mentions(page_dir: Path, code: str) -> bool:
    return any(
        code in p.read_text(encoding="utf-8", errors="ignore") for p in sorted(page_dir.rglob("*")) if p.is_file()
    )


def review_pages_mentioning(root: Path, code: str) -> list[Path]:
    """The review page directories under the data root whose files mention session `code`."""
    base = layout.review_root(root)
    if not base.is_dir():
        return []
    return [d for d in sorted(base.iterdir()) if d.is_dir() and _mentions(d, code)]
