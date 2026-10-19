"""What intake checks before it moves anything into a corpus: the corpus's manifest as it is, and
the staged manifest and corpus.toml as `tkh eval` and the registry will read them."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from .. import manifest
from ..contracts.registry import RegistryError, load_corpus_file
from ..manifest import ManifestError
from .errors import IntakeError
from .stage import Staged


def manifest_ids(path: Path, register: Mapping[str, str]) -> list[str]:
    """The clip ids of a manifest (none if it does not exist yet); an invalid row is refused here,
    naming the corpus's own file, before anything is staged."""
    if not path.exists():
        return []
    try:
        return [c.id for c in manifest.load(path, register=register)]
    except ManifestError as e:
        raise IntakeError(f"the corpus manifest has a bad row; fix it, then run again: {e}") from e


def check_staged(staged: Staged, *, register: Mapping[str, str], pack: Path) -> None:
    """The staged manifest and corpus.toml, as `check_new_files` checks them."""
    check_new_files(staged.manifest, staged.corpus_toml, register=register, pack=pack)


def check_new_files(manifest_path: Path, corpus_toml: Path, *, register: Mapping[str, str], pack: Path) -> None:
    """A corpus's new manifest loads with the data register and has unique ids (`tkh eval`
    refuses duplicates), and its new corpus.toml loads against the pack. Also `tkh adapt`'s check."""
    try:
        ids = [c.id for c in manifest.load(manifest_path, register=register)]
    except ManifestError as e:
        raise IntakeError(f"the new manifest would not load: {e}") from e
    repeated = sorted(i for i, n in Counter(ids).items() if n > 1)
    if repeated:
        raise IntakeError(f"clip ids already in the manifest: {', '.join(repeated)}")
    try:
        load_corpus_file(corpus_toml, pack=pack)
    except RegistryError as e:
        raise IntakeError(f"the new corpus.toml would not load: {e}") from e
