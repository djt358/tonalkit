"""The data root (`$TONEKIT_DATA`): where corpora, their speakers and the stale markers live."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from functools import cached_property
from pathlib import Path

from ..contracts.pack import PackInfo, load_pack_info
from ..contracts.registry import Kind, Split, StaleMarker, data_root
from ..manifest import ClipSet
from . import stale
from .corpus import Corpus, load_corpus
from .layout import corpus_ids, existing_corpus_dir
from .select import select
from .selection import Selection


class DataRoot:
    """The data root: `DataRoot(path)`, else `$TONEKIT_DATA`, else `~/tonekit-data`. Corpora are
    checked against the accents of `pack` (a pack TOML path or `PackInfo`; default
    packs/cmn/cmn.toml), the pack their clips are graded with. Nothing is created or read until
    you ask."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        pack: str | Path | PackInfo | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.path = data_root(path, environ=environ)
        self._pack = pack

    def __repr__(self) -> str:
        return f"DataRoot({str(self.path)!r})"

    @property
    def corpora_dir(self) -> Path:
        return self.path / "corpora"

    @cached_property
    def pack(self) -> PackInfo:
        """The pack the corpora's accents are checked against (read once, when first needed)."""
        return self._pack if isinstance(self._pack, PackInfo) else load_pack_info(self._pack)

    def corpus_ids(self) -> list[str]:
        """The ids of the corpora here, sorted."""
        return corpus_ids(self.path)

    def corpus(self, corpus_id: str) -> Corpus:
        """Load one corpus (its corpus.toml; its manifest when `.clips` is read). Raises
        `RegistryError` naming the file at fault."""
        return load_corpus(existing_corpus_dir(self.path, corpus_id), self.pack)

    def select(
        self,
        corpora: Sequence[str] = ("*",),
        *,
        kinds: Collection[Kind] | None = None,
        splits: Collection[Split] | None = None,
        sets: Collection[ClipSet] | None = None,
    ) -> Selection:
        """See `registry.select.select`."""
        return select(self, corpora, kinds=kinds, splits=splits, sets=sets)

    # ---- stale markers ----------------------------------------------------------------------

    def mark_stale(self, corpus_id: str, reason: str, *, now: datetime | None = None) -> StaleMarker:
        """Mark what was computed from the corpus (the scoreboard, a calibration fitted on it) as
        stale; returns the marker as written. Purge and relabel call `stale.mark_stale`."""
        return stale.mark(self.path, corpus_id, reason, now=now)

    def stale_marker(self, corpus_id: str) -> StaleMarker | None:
        return stale.read_marker(self.path, corpus_id)

    def is_stale(self, corpus_id: str) -> bool:
        return stale.is_stale(self.path, corpus_id)

    def clear_stale(self, corpus_id: str, *, marked_before: datetime) -> StaleMarker | None:
        """The run that began at `marked_before` recomputed from the corpus: see
        `stale.clear_stale`. Returns what is still stale (None: nothing)."""
        return stale.clear_stale(self.path, corpus_id, marked_before=marked_before)

    def stale_corpus_ids(self) -> list[str]:
        return stale.stale_corpus_ids(self.path)
