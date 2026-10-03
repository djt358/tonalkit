"""`tkh deck approve`: the rows DJ's decision makes, with the fingerprints of the cards as the built
deck has them now (R91)."""

from __future__ import annotations

from collections.abc import Sequence

from .approvals import Approval
from .errors import BuildError
from .fingerprint import card_fingerprint


def decisions(
    cards: Sequence[dict], ids: Sequence[str], *, everything: bool, rejected: bool = False, note: str = ""
) -> list[Approval]:
    """An approval (or, with `rejected`, a rejection) for each card named in `ids`, or for every card
    of `cards` with `everything`. Naming a card the deck does not have is an error and makes no rows."""
    if everything == bool(ids):
        raise BuildError("name the cards to approve, or give --all (not both)")
    known = {c["id"]: c for c in cards}
    if missing := [i for i in dict.fromkeys(ids) if i not in known]:
        raise BuildError(f"not cards of the deck: {', '.join(missing)} (the audit sheet lists every id)")
    chosen = list(cards) if everything else [known[i] for i in dict.fromkeys(ids)]
    decision = "rejected" if rejected else "approved"
    return [Approval(c["id"], card_fingerprint(c), decision, note) for c in chosen]
