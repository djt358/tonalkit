"""Purge and the reports under the data root: a report lists each clip by id (`<CODE>-<card>`)
with its scores, which is "kept from" the recordings, so a report that mentions the session goes.
Reports are made again by the next `tkh eval`."""

from __future__ import annotations

from pathlib import Path

REPORTS = "reports"


def reports_mentioning(root: Path, code: str) -> list[Path]:
    """The files under `<root>/reports` whose text mentions session `code`."""
    folder = root / REPORTS
    if not folder.is_dir():
        return []
    return [
        p for p in sorted(folder.rglob("*")) if p.is_file() and code in p.read_text(encoding="utf-8", errors="ignore")
    ]


def remove_files(paths: list[Path]) -> int:
    for p in paths:
        p.unlink()
    return len(paths)
