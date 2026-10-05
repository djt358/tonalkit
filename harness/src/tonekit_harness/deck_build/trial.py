"""Trying cards against the contract before they join the deck: a tiny deck of the cards goes
through `parse_deck`, so a candidate is judged by exactly the rules the finished deck must pass."""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..contracts.deck import DeckError, parse_deck
from .contract_view import contract_card

_META = {"id": "trial", "lect": "cmn", "version": 1, "title": "trial"}
_CARD_PREFIX = re.compile(r"^card '[^']*': ")  # the trial cards' ids mean nothing to the reader


def problems(cards: Sequence[dict]) -> list[str]:
    """What the contract says is wrong with `cards` taken as a deck of their own (empty if
    nothing), without the cards' ids."""
    try:
        parse_deck({"deck": _META, "card": [contract_card(c) for c in cards]}, source="trial")
    except DeckError as e:
        return [_CARD_PREFIX.sub("", line.strip()) for line in str(e).splitlines()[1:]]
    return []


def reading_problems(card: dict) -> list[str]:
    """What is wrong with the card's own reading (pinyin, tones, sandhi), apart from any pairing:
    the card is tried alone in a set that has no pairs."""
    alone = {k: v for k, v in card.items() if k != "pair"} | {"set": "register"}
    return problems([alone])
