"""Assembling the deck from its sources, in the order the cards are read: the register warm-up
first (eight clips are what a speaker's register needs), then the gate, then the sandhi contrasts,
then the other diagnostics. The finished deck goes through the contract models; a deck that
`parse_deck` refuses is never written."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts.deck import Deck, parse_deck
from .contract_view import contract_card, dropped_fields
from .errors import BuildError
from .gate import GateBuild, build_gate, standin_rows
from .gmeasure import read_gmeasure
from .lexicon import load_lexicon
from .minimal_set import minimal_cards
from .single_cards import single_cards
from .t23_set import t23_cards

META = "deck.toml"
LEXICON = "tone_variants.csv"
STANDIN = "gate_standin.csv"


@dataclass
class Built:
    data: dict  # {"deck": {...}, "card": [...]}: what the files are written from
    deck: Deck  # the same, validated by the contract
    flags: dict[str, str]  # card id -> what DJ should look at
    gate: GateBuild
    dropped: list[str] = field(default_factory=list)  # newer card fields the model cannot hold yet

    def report_lines(self) -> list[str]:
        lines = self.gate.report_lines()
        if self.dropped:
            lines.append(
                f"note: the contract model has no {', '.join(self.dropped)} yet, so the TOML leaves "
                "it out and the JSON keeps it"
            )
        return lines


def _meta(sources: Path) -> dict:
    path = sources / META
    try:
        deck = tomllib.loads(path.read_text(encoding="utf-8"))["deck"]
    except (OSError, tomllib.TOMLDecodeError, KeyError) as e:
        raise BuildError(f"{path}: cannot read the [deck] table ({e})") from e
    return deck


def _gate(sources: Path, gmeasure: Path | None, gmeasure_map: Mapping[str, str] | None, pairs: int) -> GateBuild:
    lexicon = load_lexicon(sources / LEXICON)
    if gmeasure is None:
        return build_gate(standin_rows(sources / STANDIN), lexicon, pairs, source=f"the stand-in {STANDIN}")
    rows, no_phrase = read_gmeasure(gmeasure, gmeasure_map)
    return build_gate(rows, lexicon, pairs, earlier_unusable=list(no_phrase), source=f"DJ's table {gmeasure.name}")


def build_deck(
    sources: str | Path,
    *,
    gmeasure: str | Path | None = None,
    gmeasure_map: Mapping[str, str] | None = None,
    gate_pairs: int = 20,
) -> Built:
    """The deck made from the sources in `sources`. `gmeasure` replaces the stand-in gate phrases
    with the rows of DJ's g_measure table. Raises `BuildError` for a source that cannot be read
    or a gate with too few pairs, and `DeckError` if the finished deck breaks the contract."""
    sources = Path(sources)
    gate = _gate(sources, Path(gmeasure) if gmeasure else None, gmeasure_map, gate_pairs)
    flags = dict(gate.flags)
    cards: list[dict] = []

    def add(part: tuple[list[dict], dict[str, str]]) -> None:
        cards.extend(part[0])
        flags.update(part[1])

    add(single_cards(sources / "register.csv", set_="register", prefix="r", context="isolated"))
    cards.extend(gate.cards)
    add(single_cards(sources / "diag_context.csv", set_="diag_context", prefix="x", context=None))
    add(t23_cards(sources / "diag_t23.csv"))
    add(minimal_cards(sources / "diag_minimal.csv"))
    add(single_cards(sources / "diag_count.csv", set_="diag_count", prefix="n", context="phrase"))
    data = {"deck": _meta(sources), "card": cards}
    deck = parse_deck({"deck": data["deck"], "card": [contract_card(c) for c in cards]}, source="deck")
    return Built(data, deck, flags, gate, dropped_fields())
