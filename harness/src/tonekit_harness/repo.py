"""Where the repository is, for the defaults that name files in it (the cmn pack, `kit/schema`)."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """The repository root, found from this file (the harness runs from a checkout, installed
    editable by `uv sync`)."""
    root = Path(__file__).resolve().parents[3]
    if not (root / "packs").is_dir():
        raise RuntimeError(f"{root} is not the tonekit repository root (no packs/ directory)")
    return root
