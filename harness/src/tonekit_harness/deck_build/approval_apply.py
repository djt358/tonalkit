"""Applying DJ's approvals to the cards the builder made (R91). A row counts only while its
fingerprint is the card's: `approved` makes the card `approved`, `rejected` drops it. A row whose
fingerprint no longer matches is stale, whichever its decision: the card changed after DJ looked, so
it stays `unverified` (and is reported). A row for a card that is not in the deck is an error."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .approvals import Approval
from .errors import BuildError
from .fingerprint import card_fingerprint


@dataclass(frozen=True)
class Stale:
    approval: Approval
    now: str  # the card's fingerprint today

    def line(self) -> str:
        a = self.approval
        word = "approval" if a.decision == "approved" else "rejection"
        return f"stale {word} {a.card_id} ({a.decision} for {a.fingerprint}, the card is now {self.now}): it stays unverified"


@dataclass
class Applied:
    cards: list[dict]  # approved cards marked so, rejected cards gone
    approved: list[str] = field(default_factory=list)
    rejected: list[Approval] = field(default_factory=list)
    stale: list[Stale] = field(default_factory=list)

    def report_lines(self) -> list[str]:
        lines = [f"approvals: {len(self.approved)} of {len(self.cards)} cards approved"]
        lines += [f"  rejected {a.card_id} ({a.where or 'approvals file'}): dropped from the deck" for a in self.rejected]
        lines += [f"  {s.line()}" for s in self.stale]
        return lines


def apply_approvals(cards: Sequence[dict], approvals: Sequence[Approval]) -> Applied:
    ids = {c["id"] for c in cards}
    unknown = [a for a in approvals if a.card_id not in ids]
    if unknown:
        raise BuildError(
            "\n".join(f"{a.where or 'approvals file'}: {a.card_id} is not a card of the deck (delete the row)" for a in unknown)
        )
    by_id = {a.card_id: a for a in approvals}
    out = Applied([])
    for card in cards:
        row = by_id.get(card["id"])
        now = card_fingerprint(card)
        if row is None:
            out.cards.append(card)
        elif row.fingerprint != now:
            out.stale.append(Stale(row, now))
            out.cards.append(card)
        elif row.decision == "rejected":
            out.rejected.append(row)
        else:
            out.cards.append({**card, "status": "approved"})
            out.approved.append(card["id"])
    return out
