"""Whether a file or folder is a bundle of one session: its name carries the code as a word (the
kit names zips `tonekit-<deck>-<CODE>.zip`; a second download may add " 2" or "(1)"), or its
session.json says so (a renamed copy)."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path

from ..contracts.bundle import SESSION_FILE


def _named(path: Path, code: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(code)}(?![A-Za-z0-9])", path.name) is not None


def _session_code(path: Path) -> str | None:
    try:
        if path.is_dir():
            raw = (path / SESSION_FILE).read_bytes()
        elif zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                raw = z.read(SESSION_FILE)
        else:
            return None
        doc = json.loads(raw)
    except (OSError, KeyError, zipfile.BadZipFile, ValueError):
        return None
    code = doc.get("session") if isinstance(doc, dict) else None
    return code if isinstance(code, str) else None


def is_session_bundle(path: Path, code: str) -> bool:
    return _named(path, code) or _session_code(path) == code


def session_bundles(folder: Path, code: str) -> list[Path]:
    """The entries of `folder` (not below it) that are bundles of `code`, sorted."""
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if is_session_bundle(p, code))
