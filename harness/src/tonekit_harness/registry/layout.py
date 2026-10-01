"""Finding corpora under a data root."""

from __future__ import annotations

from pathlib import Path

from ..contracts.registry import RegistryError, corpus_dir

MAX_IDS_SHOWN = 8


def corpus_ids_under(root: Path) -> list[str]:
    """The name of every directory in `<root>/corpora`, sorted (none if there is no such
    directory). Each is a corpus; one without a corpus.toml is an error when it is loaded."""
    corpora = root / "corpora"
    if not corpora.is_dir():
        return []
    return sorted(p.name for p in corpora.iterdir() if p.is_dir())


def existing_corpus_dir(root: Path, corpus_id: str) -> Path:
    """`<root>/corpora/<corpus_id>`, which must be a directory there. Raises `RegistryError`
    listing the corpora that do exist otherwise."""
    directory = corpus_dir(root, corpus_id)
    if Path(corpus_id).name == corpus_id and corpus_id not in {"", ".", ".."} and directory.is_dir():
        return directory
    raise RegistryError(f"{directory}: no such corpus (have: {_listed(corpus_ids_under(root))})")


def _listed(ids: list[str]) -> str:
    if not ids:
        return "none"
    shown = ", ".join(ids[:MAX_IDS_SHOWN])
    return shown if len(ids) <= MAX_IDS_SHOWN else f"{shown}, and {len(ids) - MAX_IDS_SHOWN} more"
