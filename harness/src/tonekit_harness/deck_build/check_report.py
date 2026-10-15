"""`tkh deck check`: the contract's verdict on a deck file, with a summary a person can read."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..contracts.deck import Deck, DeckError, deck_sha256, load_deck, parse_deck


def load_any(path: Path, pack: str | None = None) -> Deck:
    """The deck at `path`: the contract TOML, or the kit's JSON of it."""
    if path.suffix != ".json":
        return load_deck(path, pack=pack)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise DeckError(f"{path}: cannot read as JSON: {e}") from e
    return parse_deck(data, pack=pack, source=str(path))


def _counts(name: str, counter: Counter) -> str:
    return f"  {name}: " + ", ".join(f"{k} {n}" for k, n in counter.items())


def summary(deck: Deck, path: Path) -> str:
    cards = deck.card
    pairs = {(c.set, c.pair) for c in cards if c.pair is not None}
    traditional = sum(getattr(c, "text_traditional", None) is not None for c in cards)
    noted = [c for c in cards if c.prompt_note]
    traditional_notes = sum(getattr(c, "prompt_note_traditional", None) is not None for c in noted)
    lines = [
        f"OK {path}",
        f"  deck {deck.deck.id} ({deck.deck.lect}, version {deck.deck.version}): {len(cards)} cards, {len(pairs)} pairs",
        _counts("sets", Counter(c.set for c in cards)),
        _counts("contexts", Counter(c.context for c in cards)),
        _counts("labels", Counter(c.label for c in cards)),
        _counts("status", Counter(c.status for c in cards)),
        f"  traditional text on {traditional} of {len(cards)} cards",
        f"  traditional note on {traditional_notes} of {len(noted)} cards that have a note",
        f"  sha256 {deck_sha256(path)}",
    ]
    return "\n".join(lines)


def problem_report(error: DeckError) -> str:
    """The contract's problem lines, with how many there are."""
    lines = str(error).splitlines()
    count = max(len(lines) - 1, 1)
    return "\n".join([*lines, f"{count} problem{'s' if count != 1 else ''}"])


def ship_report(path: Path, problems: list[str]) -> str:
    """Why the deck at `path` cannot ship, with how many reasons there are."""
    count = len(problems)
    return "\n".join(
        [f"NOT READY TO SHIP {path}", *(f"  {p}" for p in problems), f"{count} problem{'s' if count != 1 else ''}"]
    )
