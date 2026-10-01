"""What `tkh corpora` says about a corpus."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import get_args

from ..contracts.registry import RegistryError, Split
from .root import DataRoot
from .stale import StaleMarker


@dataclass(frozen=True)
class CorpusSummary:
    id: str
    kind: str | None = None
    source: str | None = None
    speakers: dict[str, int] = field(default_factory=dict)  # split -> speakers, in split order
    clips: dict[str, int] = field(default_factory=dict)  # set -> clips, in order of appearance
    stale: StaleMarker | None = None
    error: str | None = None  # why the corpus could not be read; the other fields may be empty


def summarise(root: DataRoot, corpus_id: str) -> CorpusSummary:
    """One corpus's summary. A corpus that cannot be read (its corpus.toml, manifest or stale
    marker) gets a summary carrying the error, so a listing can show it instead of stopping."""
    try:
        corpus = root.corpus(corpus_id)
    except RegistryError as e:
        return CorpusSummary(corpus_id, error=str(e))
    meta = corpus.meta
    by_split = Counter(s.split for s in corpus.file.speaker)
    speakers = {split: by_split[split] for split in get_args(Split) if by_split[split]}
    try:
        by_set = Counter(i.clip.set for i in corpus.clips)
        stale = root.stale_marker(corpus_id)
        return CorpusSummary(corpus_id, meta.kind, meta.source, speakers, dict(by_set), stale)
    except RegistryError as e:
        return CorpusSummary(corpus_id, meta.kind, meta.source, speakers, error=str(e))
