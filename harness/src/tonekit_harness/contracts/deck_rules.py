"""The deck rules that look across cards, at the pack, or at the pinyin (contracts.md section 1).
`deck.Deck` runs them once its cards pass their own checks; each returns problem lines."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING

from .deck_sets import PAIR_SETS
from .lects import LectError, LectRules, lect_rules
from .pack import PackInfo

if TYPE_CHECKING:
    from .deck import Card, Deck


def fmt(tones: Sequence[str]) -> str:
    return "-".join(tones)


def deck_problems(deck: Deck, pack: PackInfo) -> list[str]:
    problems = _duplicate_ids(deck.card)
    if deck.deck.lect != pack.lect:
        problems.append(f"deck lect {deck.deck.lect!r} but the pack is for {pack.lect!r}")
    for card in deck.card:
        problems += _pack_tone_problems(card, pack)
    try:
        rules = lect_rules(deck.deck.lect)
    except LectError as e:
        return [*problems, str(e)]
    for card in deck.card:
        problems += _reading_problems(card, rules)
    return problems + _pair_problems(deck.card) + _minimal_problems(deck.card)


def _duplicate_ids(cards: Sequence[Card]) -> list[str]:
    seen: set[str] = set()
    out = []
    for card in cards:
        if card.id in seen:
            out.append(f"duplicate card id {card.id!r}")
        seen.add(card.id)
    return out


def _pack_tone_problems(card: Card, pack: PackInfo) -> list[str]:
    known = ", ".join(sorted(pack.tone_ids))
    places = [("intended.tones", card.intended.tones), ("produced_tones", card.produced_tones)]
    places += [(f"distractor {d.id!r}", d.tones) for d in card.distractors]
    return [
        f"card {card.id!r}: {where}: {tone!r} is not a tone id of the pack (known: {known})"
        for where, tones in places
        for tone in dict.fromkeys(tones)
        if tone not in pack.tone_ids
    ]


def _reading_problems(card: Card, rules: LectRules) -> list[str]:
    """The card's pinyin, citation pinyin, produced tones and sandhi must agree. The sandhi check
    is on `produced_tones` (the reading the card shows and asks for), which is `intended.tones` on
    a correct card; an error card is a different word with its own citation pinyin."""
    try:
        citation = rules.parse_pinyin(card.citation_pinyin)
    except ValueError as e:
        return [f"card {card.id!r}: citation_pinyin: {e}"]
    try:
        shown = rules.parse_pinyin(card.pinyin)
    except ValueError as e:
        return [f"card {card.id!r}: pinyin: {e}"]
    if len(citation) != len(card.intended.tones):
        return [
            f"card {card.id!r}: citation_pinyin has {len(citation)} syllables "
            f"but intended has {len(card.intended.tones)} tones"
        ]
    problems = []
    if [s.tone for s in shown] != card.produced_tones:
        problems.append(
            f"card {card.id!r}: pinyin is {fmt([s.tone for s in shown])} "
            f"but produced_tones are {fmt(card.produced_tones)}"
        )
    citation_tones = [s.tone for s in citation]
    options = rules.surface_options(citation_tones, [s.base for s in citation], card.context, card.text)
    if tuple(card.produced_tones) not in options:
        problems.append(_sandhi_problem(card, citation_tones, options))
    return problems


def _sandhi_problem(card: Card, citation_tones: list[str], options: set[tuple[str, ...]]) -> str:
    produced = fmt(card.produced_tones)
    if card.context == "isolated":
        return (
            f"card {card.id!r}: isolated reading {produced} is not the citation tones of "
            f"{card.citation_pinyin!r} ({fmt(citation_tones)})"
        )
    acceptable = " or ".join(fmt(o) for o in sorted(options))
    return (
        f"card {card.id!r}: phrase reading {produced} is not a sandhi reading of "
        f"{card.citation_pinyin!r} ({acceptable})"
    )


def _pair_problems(cards: Sequence[Card]) -> list[str]:
    """Each pair of a pair set (within the set) is one correct and one tone_error card of the same
    intended tones. Elsewhere `pair` only groups (R81)."""
    pairs: dict[tuple[str, str], list[Card]] = defaultdict(list)
    for card in cards:
        if card.pair is not None and card.set in PAIR_SETS:
            pairs[(card.set, card.pair)].append(card)
    problems = []
    for (set_, pair), members in pairs.items():
        where = f"pair {pair!r} (set {set_})"
        correct = [c for c in members if c.label == "correct"]
        errors = [c for c in members if c.label == "tone_error"]
        others = [c.id for c in members if c.label == "n/a"]
        if others:
            problems.append(f"{where} has an n/a card: {', '.join(others)}")
        if len(correct) != 1 or len(errors) != 1:
            problems.append(
                f"{where} has {len(correct)} correct and {len(errors)} tone_error cards; "
                "it needs one of each"
            )
        elif errors[0].intended.tones != correct[0].intended.tones:
            problems.append(
                f"{where}: {errors[0].id} intends {fmt(errors[0].intended.tones)} "
                f"but {correct[0].id} intends {fmt(correct[0].intended.tones)}"
            )
    return problems


def _minimal_problems(cards: Sequence[Card]) -> list[str]:
    """A `diag_minimal` card names, as a distractor, the intended reading of another member of the
    deck's minimal sets: the candidates a recording of it is decoded against (R76, R81)."""
    members = [c for c in cards if c.set == "diag_minimal"]
    problems = []
    for card in members:
        others = {m.intended.id for m in members if m.intended.id != card.intended.id}
        if not others.intersection(d.id for d in card.distractors):
            listed = ", ".join(repr(d.id) for d in card.distractors) or "none"
            problems.append(
                f"card {card.id!r}: a diag_minimal card needs a distractor that is another "
                f"diag_minimal card's intended id (its distractors: {listed}; "
                f"the other cards intend: {', '.join(sorted(map(repr, others))) or 'nothing'})"
            )
    return problems
