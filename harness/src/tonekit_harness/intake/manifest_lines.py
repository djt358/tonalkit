"""A manifest's rows picked out line by line (a session's for purge, relabelled ones for relabel):
every other line, valid or not, stays exactly as it was (neither may rewrite rows it does not
own)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping


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


def rewritten(text: str, rows: Mapping[str, str | None]) -> str:
    """`text` with the row of each id in `rows` replaced by its new JSON (None: removed); every
    other line stays exactly as it was (relabel changes only the rows it relabels)."""
    out = []
    for line in text.splitlines(keepends=True):
        row = _row(line) if line.strip() else None
        cid = row.get("id") if row is not None else None
        if not isinstance(cid, str) or cid not in rows:
            out.append(line)
        elif (new := rows[cid]) is not None:
            out.append(new + "\n")
    return "".join(out)


def appended(text: str, rows: list[str]) -> str:
    """`text` with one JSON row per line added at the end (a missing final newline is added)."""
    if text and not text.endswith("\n"):
        text += "\n"
    return text + "".join(row + "\n" for row in rows)
