"""What each clip's card showed the speaker: its text in both scripts, its pinyin, its note, and
the twin it was paired with. The kit records card ids only, so this comes from the deck the
session was recorded with (found by its hash, as intake finds it) and the session's own answers
(which script and whether pinyin was shown)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ..contracts.bundle import Session
from ..contracts.deck import Card, Deck
from ..contracts.deck_sets import PAIR_SETS
from ..intake import layout
from ..intake.deck_lookup import find_deck
from ..intake.errors import IntakeError
from ..relabel.state import CorpusState, session_of


class ReviewError(ValueError):
    """The page could not be made; nothing was written."""


@dataclass(frozen=True)
class Shown:
    card: Card
    twin: Card | None  # the other card of its pair, in a pair set
    script: str  # "simplified" or "traditional": what the speaker read
    reading: str  # "hanzi" or "hanzi+pinyin"


def _session(corpus: Path, code: str) -> Session:
    path = layout.session_copy(corpus, code)
    try:
        return Session.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as e:
        raise ReviewError(f"{path}: cannot read the session's session.json copy: {e}") from e


def _twin(card: Card, deck: Deck) -> Card | None:
    if card.set not in PAIR_SETS:
        return None
    return next((c for c in deck.card if c.id != card.id and (c.set, c.pair) == (card.set, card.pair)), None)


def shown_cards(state: CorpusState, *, repo: Path, deck: Path | None = None) -> dict[str, Shown]:
    """Clip id -> what its card showed, for every clip of a volunteer session with a deck card.
    Raises `ReviewError` when a session's deck cannot be found (pass `deck`, the file the kit
    served, as for intake)."""
    sessions: dict[str, Session] = {}
    decks: dict[tuple[str, str], Deck] = {}
    out: dict[str, Shown] = {}
    for cid, clip in state.clips.items():
        code = session_of(cid)
        if code is None or clip.original.card is None:
            continue
        if code not in sessions:
            sessions[code] = _session(state.corpus, code)
        session = sessions[code]
        key = (session.deck.id, session.deck.sha256)
        if key not in decks:
            try:
                decks[key] = find_deck(session.deck, repo=repo, explicit=deck).deck
            except IntakeError as e:
                raise ReviewError(f"session {code}: {e}") from e
        cards = {c.id: c for c in decks[key].card}
        card = cards.get(clip.original.card)
        if card is None:
            raise ReviewError(f"clip {cid}: card {clip.original.card!r} is not in deck {session.deck.id!r}")
        out[cid] = Shown(card, _twin(card, decks[key]), session.speaker.script, session.speaker.reading)
    return out
