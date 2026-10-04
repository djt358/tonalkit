"""A manifest's rows of one session, picked out line by line: every other line, valid or not,
stays exactly as it was (purge must not rewrite rows it does not own)."""

from __future__ import annotations

import json
from collections.abc import Callable


def _row(line: str) -> dict | None:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def without_rows(text: str, is_session: Callable[[dict], bool]) -> tuple[str, int]:
    """`text` without the rows `is_session` picks, and how many there were."""
    kept, removed = [], 0
    for line in text.splitlines(keepends=True):
        row = _row(line) if line.strip() else None
        if row is not None and is_session(row):
            removed += 1
        else:
            kept.append(line)
    return "".join(kept), removed


def appended(text: str, rows: list[str]) -> str:
    """`text` with one JSON row per line added at the end (a missing final newline is added)."""
    if text and not text.endswith("\n"):
        text += "\n"
    return text + "".join(row + "\n" for row in rows)
