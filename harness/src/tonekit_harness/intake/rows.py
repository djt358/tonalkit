"""One manifest row per kept clip of a session, joined to its deck card (docs/s05/contracts.md
section 4). The kit records card ids only; the set, pair, label, readings and context come from
the deck the speaker read. Skipped cards get no row.

A card of a pair set (`gate`, `diag_t23`) whose twin was not recorded is kept out as well: such
pairs are one correct and one deliberate-error reading (R81), and `tkh eval` grades a gate pair
only whole.

`needs_listen` stays false. harness/corpus/PROTOCOL.md keeps it for gate failures and adversarial
finds; a deliberate error read as the correct word is exactly a "tone-error clip accepted" failure
in the `tkh eval` report, which is the list to listen to. Flagging every error card would flag a
third of each session and say nothing."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..contracts.bundle import Session
from ..contracts.deck import Card, Deck
from ..contracts.deck_sets import PAIR_SETS
from ..contracts.registry import volunteer_speaker_id
from ..manifest import Clip
from . import layout
from .conditions import KIT_CONDITION
from .errors import IntakeError


@dataclass(frozen=True)
class Joined:
    rows: list[Clip]  # in deck order
    kept_out: dict[str, str]  # card id -> why it has no row although it was recorded


def _twin(card: Card, cards: dict[str, Card]) -> Card | None:
    if card.set not in PAIR_SETS:
        return None
    return next((c for c in cards.values() if c.id != card.id and (c.set, c.pair) == (card.set, card.pair)), None)


def _checked_cards(session: Session, deck: Deck) -> dict[str, Card]:
    cards = {c.id: c for c in deck.card}
    named = [c.card for c in session.clips] + list(session.skipped)
    unknown = [c for c in named if c not in cards]
    if unknown:
        raise IntakeError(f"the bundle names cards deck {deck.deck.id!r} does not have: {', '.join(unknown)}")
    unapproved = [c.card for c in session.clips if cards[c.card].status != "approved"]
    if unapproved:
        raise IntakeError(
            f"cards not approved in deck {deck.deck.id!r} (a ?dev=1 session?): {', '.join(unapproved)}; "
            "intake takes approved cards only"
        )
    return cards


def join_session(session: Session, deck: Deck, *, source: str, path_of: Callable[[str], str]) -> Joined:
    """The rows of `session`'s kept clips. `source` is the corpus's (R80); `path_of(card)` is the
    clip's path relative to the manifest."""
    cards = _checked_cards(session, deck)
    recorded = {c.card: c for c in session.clips}
    code = session.session
    rows, kept_out = [], {}
    for card in deck.card:
        clip = recorded.get(card.id)
        if clip is None:
            continue
        twin = _twin(card, cards)
        if twin is not None and twin.id not in recorded:
            kept_out[card.id] = f"its {card.set} twin {twin.id} was not recorded"
            continue
        rows.append(
            Clip(
                id=layout.clip_id(code, card.id),
                path=path_of(card.id),
                speaker=volunteer_speaker_id(code),
                set=card.set,
                pair=layout.pair_id(code, card.pair),
                label=card.label,
                intended=card.intended,
                distractors=card.distractors,
                produced_tones=card.produced_tones,
                condition=KIT_CONDITION,
                source=source,
                needs_listen=False,
                card=card.id,
                deck=deck.deck.id,
                take=clip.takes,
                context=card.context,
            )
        )
    return Joined(rows=rows, kept_out=kept_out)
