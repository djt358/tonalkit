"""Write a text file so that a reader never sees it half written."""

from __future__ import annotations

import os
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> None:
    """Write `text` to `path` (UTF-8; parent directories are created) through a temporary file in
    the same directory and an `os.replace`, which is atomic."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
