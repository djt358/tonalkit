"""Keeping graded pairs whole after a relabel. A pair of a pair set (`gate`, `diag_t23`) is one
correct and one tone_error reading of the same words (R66, R81), and the gate grades it whole. A
relabel can leave it otherwise: an error card read as the correct word makes two correct readings;
an excluded clip leaves one. Such a pair is a half pair, as intake would call it, and the clips
leave it: their `pair` is cleared, which keeps them out of the gate's pairs (`metrics`), while the
rows stay for fitting and the other diagnostics (ruling R112). A pair the relabel leaves whole, or
does not touch, keeps its id."""

from __future__ import annotations

from collections.abc import Mapping

from ..contracts.deck_sets import PAIR_SETS
from ..manifest import Clip


def _groups(originals: Mapping[str, Clip]) -> dict[tuple[str, str], list[str]]:
    groups: dict[tuple[str, str], list[str]] = {}
    for cid, row in originals.items():
        if row.set in PAIR_SETS and row.pair is not None:
            groups.setdefault((row.set, row.pair), []).append(cid)
    return groups


def twins(originals: Mapping[str, Clip]) -> dict[str, str]:
    """Clip id -> the id of the other clip of its pair, for the pairs of pair sets that are whole
    (two clips) as intake wrote them."""
    out = {}
    for members in _groups(originals).values():
        if len(members) == 2:
            a, b = members
            out[a], out[b] = b, a
    return out


def _whole(rows: list[Clip | None]) -> bool:
    return len(rows) == 2 and all(r is not None for r in rows) and sorted(r.label for r in rows) == [
        "correct",
        "tone_error",
    ]


def with_pairs(target: Mapping[str, Clip | None], originals: Mapping[str, Clip]) -> dict[str, Clip | None]:
    """`target` (clip id -> row, None if excluded; rebuilt from `originals`, which keep their
    pairs) with the pair cleared on the clips of every pair the relabel changed and left without
    one correct and one tone_error reading."""
    out = dict(target)
    for members in _groups(originals).values():
        rows = [target.get(cid) for cid in members]
        touched = any(target.get(cid) != originals[cid] for cid in members)
        if not touched or _whole(rows):
            continue
        for cid, row in zip(members, rows, strict=True):
            if row is not None:
                out[cid] = row.model_copy(update={"pair": None})
    return out


def half_pairs(target: Mapping[str, Clip | None], originals: Mapping[str, Clip]) -> list[str]:
    """The pair ids (as the rows name them) that `with_pairs` takes apart, sorted."""
    paired = with_pairs(target, originals)
    return sorted(
        {
            originals[cid].pair or ""
            for cid, row in paired.items()
            if row is not None and originals[cid].pair is not None and row.pair is None
        }
    )
