"""The order of the page: the groups in `scorer.GROUPS` order (the scorer hearing the twin card's
reading first, then its other disagreements, the clips it is unsure of, those it never graded and
those it agrees with); within a group the most doubtful first, then corpus order. DJ listens to
every clip; the order decides which he hears while he is fresh."""

from __future__ import annotations

from collections.abc import Sequence

from .scorer import GROUPS, ScorerView


def review_order(ids: Sequence[str], views: dict[str, ScorerView]) -> list[str]:
    """`ids` (in corpus order) in page order."""
    position = {cid: i for i, cid in enumerate(ids)}

    def key(cid: str) -> tuple[int, float, int]:
        view = views[cid]
        return GROUPS.index(view.group), -(view.doubt if view.doubt is not None else 0.0), position[cid]

    return sorted(ids, key=key)
