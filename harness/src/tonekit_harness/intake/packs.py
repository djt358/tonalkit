"""The language pack of a lect in the repository, which validates a corpus's accents and grades
its clips."""

from __future__ import annotations

from pathlib import Path

from .errors import IntakeError


def pack_path(repo: Path, lect: str) -> Path:
    """`packs/<lect>/<lect>.toml`; raises `IntakeError` if the repository has none."""
    path = repo / "packs" / lect / f"{lect}.toml"
    if not path.is_file():
        raise IntakeError(f"no language pack for lect {lect!r} ({path} does not exist)")
    return path
