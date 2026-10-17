"""A corpus directory under the data root: its corpus.toml, and its manifest read on demand."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from ..contracts.pack import PackInfo
from ..contracts.registry import CorpusFile, CorpusMeta, RegistryError, Speaker, load_corpus_file
from .errors import reason
from .items import CorpusClip
from .rows import corpus_clips


@dataclass(frozen=True, eq=False)
class Corpus:
    """A corpus whose corpus.toml has been read and checked. The manifest is read (and joined to
    the speakers) the first time `clips` is asked for, so listing or filtering corpora never pays
    for, or trips over, a manifest it does not need."""

    directory: Path
    file: CorpusFile

    @property
    def meta(self) -> CorpusMeta:
        return self.file.corpus

    @cached_property
    def speakers(self) -> dict[str, Speaker]:
        return {s.id: s for s in self.file.speaker}

    @property
    def manifest_path(self) -> Path:
        return self.directory / self.meta.manifest

    @cached_property
    def clips(self) -> tuple[CorpusClip, ...]:
        return corpus_clips(self.meta, self.speakers, self.manifest_path)


def load_corpus(directory: Path, pack: PackInfo | None = None) -> Corpus:
    """Read `<directory>/corpus.toml`, its speakers' accents checked against `pack` (default:
    packs/cmn/cmn.toml). Raises `RegistryError` naming the file if it is missing, unreadable or
    invalid, or if its id is not the name of the directory it is in (the directory is how a corpus
    is found, and the id is what a selection and a gate name it by)."""
    path = directory / "corpus.toml"
    if not path.is_file():
        raise RegistryError(f"{path}: no corpus.toml (every directory under corpora/ is a corpus)")
    try:
        file = load_corpus_file(path, pack=pack)
    except (OSError, UnicodeDecodeError) as e:
        raise RegistryError(f"{path}: cannot read the corpus file: {reason(e)}") from e
    if file.corpus.id != directory.name:
        raise RegistryError(
            f"{path}: corpus id {file.corpus.id!r} does not match its directory name {directory.name!r}"
        )
    return Corpus(directory, file)
