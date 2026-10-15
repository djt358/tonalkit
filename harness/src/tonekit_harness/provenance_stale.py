"""Ruling R113: a stale calibration can't ship. A pack's PROVENANCE.toml lists the corpora its fit
used (`corpora = ["volunteers-s05-v1"]`), and `tkh provenance` fails while the data root holds a
stale marker (`stale/<corpus id>.json`, contracts §3: a purge or a relabel changed the corpus
after the fit) for any of them."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterable
from pathlib import Path

from .contracts.registry import CORPUS_ID_PATTERN, StaleMarker, stale_path

_CORPUS_ID = re.compile(CORPUS_ID_PATTERN)


def corpora_of(doc: dict) -> list[str] | None:
    """The corpus ids a manifest's `corpora` lists (none without the key), or None when it is not
    an array of corpus ids."""
    value = doc.get("corpora", [])
    if isinstance(value, list) and all(isinstance(c, str) and _CORPUS_ID.fullmatch(c) for c in value):
        return value
    return None


def _reasons(marker: Path) -> str:
    """How many reasons the marker gives (not the reasons: they name sessions)."""
    try:
        n = len(StaleMarker.model_validate_json(marker.read_text(encoding="utf-8")).reasons)
    except (OSError, ValueError):
        return "unreadable marker"
    return f"{n} reason{'' if n == 1 else 's'}"


def _listed(manifest: Path) -> list[str]:
    """The manifest's corpora; none for a manifest `provenance.check` reports as unreadable or
    malformed."""
    try:
        with manifest.open("rb") as f:
            return corpora_of(tomllib.load(f)) or []
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []


def stale_violations(manifests: Iterable[Path], data: Path) -> list[str]:
    """One violation per corpus a manifest lists that has a stale marker under the data root
    `data`. A data root that does not exist (CI, a fresh checkout) holds no marker, so nothing is
    stale. A file that appears more than once is checked once."""
    if not data.is_dir():
        return []
    violations: list[str] = []
    seen: set[Path] = set()
    for manifest in map(Path, manifests):
        key = manifest.resolve()
        if key in seen:
            continue
        seen.add(key)
        for corpus in _listed(manifest):
            marker = stale_path(data, corpus)
            if marker.is_file():
                violations.append(
                    f"{manifest}: fitted on corpus {corpus!r}, which is stale ({marker}: {_reasons(marker)}); "
                    "refit on the corpus as it is now before shipping (ruling R113)"
                )
    return violations
