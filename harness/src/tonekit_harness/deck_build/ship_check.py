"""`tkh deck check --ship`: whether a deck file is fit to ship in the kit (R91). Beyond the contract
(which `load_deck` has already enforced), every card must be approved, every pair of the pair sets
and every minimal set must be whole, and the register set must be big enough for a cold start."""

from __future__ import annotations

from collections import defaultdict

from ..contracts.deck import Card, Deck
from ..contracts.deck_sets import PAIR_SETS

REGISTER_MINIMUM = 8  # clips the kit takes for the speaker's register (32 syllables of cold start)
SHOWN_IDS = 12


def _ids(ids: list[str]) -> str:
    shown = ", ".join(ids[:SHOWN_IDS])
    return shown + (f" and {len(ids) - SHOWN_IDS} more" if len(ids) > SHOWN_IDS else "")


def _groups(cards: list[Card], sets) -> dict[tuple[str, str | None], list[Card]]:
    groups: dict[tuple[str, str | None], list[Card]] = defaultdict(list)
    for c in cards:
        if c.set in sets:
            groups[(c.set, c.pair)].append(c)
    return groups


def _pair_problems(cards: list[Card]) -> list[str]:
    problems = []
    for (set_, pair), members in _groups(cards, PAIR_SETS).items():
        labels = sorted(c.label for c in members)
        if pair is None or labels != ["correct", "tone_error"]:
            problems.append(f"pair {pair} of {set_} is not whole: it has {', '.join(labels) or 'no cards'}, not one correct and one tone_error")
    return problems


def _minimal_problems(cards: list[Card]) -> list[str]:
    problems = []
    for (_, group), members in _groups(cards, {"diag_minimal"}).items():
        wanted = {m.intended.id for m in members}
        if len(members) < 2:
            problems.append(f"minimal set {group} is not whole: it has one word, a set needs two or more")
        for m in members:
            missing = sorted(wanted - {m.intended.id} - {d.id for d in m.distractors})
            if missing:
                problems.append(f"minimal set {group} is not whole: {m.id} does not list {', '.join(missing)} as a distractor")
    return problems


def ship_problems(deck: Deck) -> list[str]:
    """What stops the deck from shipping, one line each; empty when it can."""
    cards = deck.card
    problems = []
    if unapproved := [c.id for c in cards if c.status != "approved"]:
        problems.append(f"{len(unapproved)} of {len(cards)} cards are not approved: {_ids(unapproved)}")
    problems += _pair_problems(cards) + _minimal_problems(cards)
    register = sum(c.set == "register" for c in cards)
    if register < REGISTER_MINIMUM:
        problems.append(f"the register set has {register} cards, the kit needs at least {REGISTER_MINIMUM}")
    return problems
