"""Appending to `purge-log.jsonl` (`contracts.registry.PurgeRecord`): the session code, when, how
many files, which corpora. Never file names: they would say what the speaker recorded (R68)."""

from __future__ import annotations

from pathlib import Path

from ..contracts.registry import PurgeRecord, purge_log_path


def append_purge_record(root: Path, record: PurgeRecord) -> Path:
    path = purge_log_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(record.model_dump_json() + "\n")
    return path
