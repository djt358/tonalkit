"""Choosing corpora, speakers and clips: the one selection mechanism every phase uses."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, get_args

from ..contracts.registry import Kind, Split
from ..manifest import ClipSet
from .errors import SelectionError
from .items import CorpusClip
from .selection import Selection

if TYPE_CHECKING:
    from .root import DataRoot

GLOB_CHARACTERS = frozenset("*?[")


def select(
    root: DataRoot,
    corpora: Sequence[str] = ("*",),
    *,
    kinds: Collection[str] | None = None,
    splits: Collection[str] | None = None,
    sets: Collection[str] | None = None,
) -> Selection:
    """The clips of the corpora matching `corpora` (ids or globs) whose corpus kind is in `kinds`,
    whose speaker's split is in `splits` and whose set is in `sets`; None means no filter. A
    union across every corpus that matches. Raises `SelectionError` for an empty or unknown filter
    value or a corpus id that is not there, and `RegistryError` for a corpus that cannot be loaded."""
    patterns = _values("corpora", corpora)
    kinds = _choice("kinds", kinds, get_args(Kind))
    splits = _choice("splits", splits, get_args(Split))
    sets = _choice("sets", sets, get_args(ClipSet))
    items: list[CorpusClip] = []
    for corpus_id in match_corpora(patterns, root.corpus_ids()):
        corpus = root.corpus(corpus_id)
        if kinds is not None and corpus.meta.kind not in kinds:
            continue
        if splits is not None and not any(s.split in splits for s in corpus.file.speaker):
            continue  # nothing of this corpus can match: do not read its manifest
        items.extend(
            i
            for i in corpus.clips
            if (splits is None or i.speaker.split in splits) and (sets is None or i.clip.set in sets)
        )
    return Selection(root.corpora_dir, tuple(items))


def match_corpora(patterns: Sequence[str], ids: Sequence[str]) -> list[str]:
    """The `ids` (in their order) that match any of `patterns`. A pattern with no glob character
    names one corpus and must be there: a mistyped id must not select nothing; a glob that matches
    nothing may."""
    matched = {i for pattern in patterns for i in ids if fnmatchcase(i, pattern)}
    for pattern in patterns:
        if not GLOB_CHARACTERS & set(pattern) and pattern not in ids:
            shown = ", ".join(ids) or "none"
            raise SelectionError(f"select: no corpus {pattern!r} (corpora: {shown})")
    return [i for i in ids if i in matched]


def _values(name: str, values: Collection[str]) -> list[str]:
    if isinstance(values, str):
        raise SelectionError(f"select: {name} must be a list, not the string {values!r}")
    values = list(values)
    if not values:
        raise SelectionError(f"select: {name} is empty (leave it out to select everything)")
    return values


def _choice(name: str, values: Collection[str] | None, allowed: tuple[str, ...]) -> frozenset[str] | None:
    if values is None:
        return None
    chosen = _values(name, values)
    unknown = [v for v in chosen if v not in allowed]
    if unknown:
        raise SelectionError(f"select: unknown {name} {unknown} (known: {', '.join(allowed)})")
    return frozenset(chosen)
