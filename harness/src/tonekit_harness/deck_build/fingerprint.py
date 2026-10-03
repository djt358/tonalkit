"""A card's fingerprint (R91): the first 12 hex digits of the sha256 of its canonical JSON without
`status`. Canonical JSON is what any language can reproduce from the card as the kit's deck file
holds it: keys sorted, no spaces after `:` or `,`, characters not escaped, UTF-8. DJ's approval is
pinned to it, so it changes when anything a volunteer sees or is graded on changes."""

from __future__ import annotations

import hashlib
import json

LENGTH = 12


def canonical_json(card: dict) -> str:
    """The card's canonical JSON without `status`."""
    body = {k: v for k, v in card.items() if k != "status"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def card_fingerprint(card: dict) -> str:
    return hashlib.sha256(canonical_json(card).encode("utf-8")).hexdigest()[:LENGTH]
