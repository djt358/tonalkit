"""The data root (`$TONEKIT_DATA`): where corpora, their speakers and the stale markers live."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from pathlib import Path

from ..contracts.registry import data_root
from . import stale
from .corpus import Corpus, load_corpus
from .layout import corpus_ids_under, existing_corpus_dir
from .select import select
from .selection import Selection


class DataRoot:
    """The data root: `DataRoot(path)`, else `$TONEKIT_DATA`, else `~/tonekit-data`. Nothing is
    created or read until you ask."""

    def __init__(self, path: str | Path | None = None, *, environ: Mapping[str, str] | None = None) -> None:
        self.path = data_root(path, environ=environ)

    def __repr__(self) -> str:
        return f"DataRoot({str(self.path)!r})"

    @property
    def corpora_dir(self) -> Path:
        return self.path / "corpora"

    def corpus_ids(self) -> list[str]:
        """The ids of the corpora here, sorted."""
        return corpus_ids_under(self.path)

    def corpus(self, corpus_id: str) -> Corpus:
        """Load one corpus (its corpus.toml; its manifest when `.clips` is read). Raises
        `RegistryError` naming the file at fault."""
        return load_corpus(existing_corpus_dir(self.path, corpus_id))

    def select(
        self,
        corpora: Sequence[str] = ("*",),
        *,
        kinds: Collection[str] | None = None,
        splits: Collection[str] | None = None,
        sets: Collection[str] | None = None,
    ) -> Selection:
        """See `registry.select.select`."""
        return select(self, corpora, kinds=kinds, splits=splits, sets=sets)

    # ---- stale markers ----------------------------------------------------------------------

    def mark_stale(self, corpus_id: str, reason: str, *, now: datetime | None = None) -> stale.StaleMarker:
        """Mark what was computed from the corpus (the scoreboard, a calibration fitted on it) as
        stale. P5's purge calls this."""
        return stale.mark_stale(self.path, corpus_id, reason, now=now)

    def stale_marker(self, corpus_id: str) -> stale.StaleMarker | None:
        return stale.read_marker(self.path, corpus_id)

    def is_stale(self, corpus_id: str) -> bool:
        return stale.is_stale(self.path, corpus_id)

    def clear_stale(self, corpus_id: str) -> bool:
        """The next successful run over the corpus calls this. Returns whether it was stale."""
        return stale.clear_stale(self.path, corpus_id)

    def stale_corpus_ids(self) -> list[str]:
        return stale.stale_corpus_ids(self.path)
