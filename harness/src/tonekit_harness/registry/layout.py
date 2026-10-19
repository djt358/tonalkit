"""Finding corpora under a data root: every directory in `<root>/corpora` is one (or a symlink
to one, such as a downloaded corpus kept on another disk); names starting with `.` are not (intake's
staging areas). The one listing intake, purge and the registry share."""

from __future__ import annotations

import os
from pathlib import Path

from ..contracts.registry import RegistryError, corpus_dir

MAX_IDS_SHOWN = 8


def corpus_ids(root: Path) -> list[str]:
    """The corpora under `root`, sorted (none if there is no `corpora` directory). A symlink is
    listed even when what it points to is missing, so an unmounted disk is an error when the
    corpus is loaded, never a corpus that silently drops out of a selection."""
    corpora = root / "corpora"
    if not corpora.is_dir():
        return []
    return sorted(
        p.name for p in corpora.iterdir() if not p.name.startswith(".") and (p.is_dir() or p.is_symlink())
    )


def existing_corpus_dir(root: Path, corpus_id: str) -> Path:
    """`<root>/corpora/<corpus_id>`, which must be a corpus there. Raises `RegistryError` listing
    the corpora that do exist otherwise, or naming the missing target of a symlink."""
    directory = corpus_dir(root, corpus_id)
    named = Path(corpus_id).name == corpus_id and not corpus_id.startswith(".") and corpus_id != ""
    if named and directory.is_dir():
        return directory
    if named and directory.is_symlink():
        raise RegistryError(
            f"{directory}: a symlink to {os.readlink(directory)}, which is not a directory (is its disk mounted?)"
        )
    raise RegistryError(f"{directory}: no such corpus (have: {_listed(corpus_ids(root))})")


def _listed(ids: list[str]) -> str:
    if not ids:
        return "none"
    shown = ", ".join(ids[:MAX_IDS_SHOWN])
    return shown if len(ids) <= MAX_IDS_SHOWN else f"{shown}, and {len(ids) - MAX_IDS_SHOWN} more"
