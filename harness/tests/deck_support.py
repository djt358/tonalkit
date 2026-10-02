"""Helpers for the deck builder tests."""

from __future__ import annotations

import pytest

from tonekit_harness.contracts.deck import DeckError, parse_deck
from tonekit_harness.deck_build.gate import GateRow
from tonekit_harness.deck_build.reading import Reading
from tonekit_harness.repo import repo_root

SOURCES = repo_root() / "kit" / "deck" / "sources"
DECK_DIR = repo_root() / "kit" / "deck"


def _probe_card(card_id: str, set_: str, text: str, pinyin: str, tone: str, **extra) -> dict:
    return {
        "id": card_id, "set": set_, "label": "correct", "text": text, "pinyin": pinyin, "citation_pinyin": pinyin,
        "context": "isolated", "intended": {"id": card_id, "tones": [tone], "labels": [text]},
        "produced_tones": [tone], **extra,
    }  # fmt: skip


# what C0's fix round adds to the contract (R74, R76, R81): a diag_context card, a traditional text,
# and a diag_minimal group of correct words that name each other as distractors
_PROBE = {
    "deck": {"id": "probe", "lect": "cmn", "version": 1, "title": "probe"},
    "card": [
        _probe_card("p1", "diag_context", "水", "shuǐ", "3", text_traditional="水"),
        _probe_card(
            "m3",
            "diag_minimal",
            "买",
            "mǎi",
            "3",
            pair="m",
            distractors=[{"id": "m4", "tones": ["4"], "labels": ["x"]}],
        ),
        _probe_card(
            "m4",
            "diag_minimal",
            "卖",
            "mài",
            "4",
            pair="m",
            distractors=[{"id": "m3", "tones": ["3"], "labels": ["x"]}],
        ),
    ],
}


def c0_fix_landed() -> bool:
    """True once the contract models take `text_traditional`, the `diag_context` set and
    `diag_minimal` groups of correct readings that name each other as distractors (C0's fix round,
    R74, R76 and R81)."""
    try:
        parse_deck(_PROBE)
    except DeckError:
        return False
    return True


needs_c0_fix = pytest.mark.skipif(
    not c0_fix_landed(),
    reason="needs C0's fix round (text_traditional, diag_context, diag_minimal pairs); rebase onto it",
)


def gate_row(text: str, citation: str, spoken: str, trad: str | None = None, where: str = "t.csv:2") -> GateRow:
    return GateRow(where, Reading(text, citation, spoken, "phrase", trad))


def small_deck_data(pairs: int = 2) -> dict:
    """A deck of the first gate pairs of the stand-in and one register card: everything the model
    holds today, so it passes `load_deck` before and after C0's fix."""
    from tonekit_harness.deck_build.cards import candidate, make_card
    from tonekit_harness.deck_build.gate import build_gate, standin_rows
    from tonekit_harness.deck_build.lexicon import load_lexicon
    from tonekit_harness.deck_build.reading import Reading

    rows = standin_rows(SOURCES / "gate_standin.csv")[:pairs]
    gate = build_gate(rows, load_lexicon(SOURCES / "tone_variants.csv"), pairs)
    register = make_card(
        id="r01", set="register", label="correct", reading=Reading("妈麻马骂", "mā má mǎ mà", "mā má mǎ mà", "isolated", "媽麻馬罵"),
        intended=candidate("r01", "mā má mǎ mà"), note="Pause.",
    )  # fmt: skip
    meta = {"id": "t-v1", "lect": "cmn", "version": 1, "title": "Test deck"}
    return {"deck": meta, "card": [register, *gate.cards]}
