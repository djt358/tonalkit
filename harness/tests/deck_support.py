"""Helpers for the deck builder tests."""

from __future__ import annotations

import pytest

from tonekit_harness.contracts.deck import DeckError, parse_deck
from tonekit_harness.deck_build.gate import GateRow
from tonekit_harness.deck_build.reading import Reading
from tonekit_harness.repo import repo_root

SOURCES = repo_root() / "kit" / "deck" / "sources"
DECK_DIR = repo_root() / "kit" / "deck"

# one card each for the three things C0's fix round adds to the contract (R74, R76)
_PROBE = {
    "deck": {"id": "probe", "lect": "cmn", "version": 1, "title": "probe"},
    "card": [
        {
            "id": f"p{i}",
            "set": "diag_context",
            "label": "correct",
            "text": "水",
            "text_traditional": "水",
            "pinyin": "shuǐ",
            "citation_pinyin": "shuǐ",
            "context": "isolated",
            "intended": {"id": f"p{i}", "tones": ["3"], "labels": ["shui"]},
            "produced_tones": ["3"],
        }
        for i in range(1)
    ]
    + [
        {
            "id": f"m{i}",
            "set": "diag_minimal",
            "pair": "m1",
            "label": "correct",
            "text": text,
            "pinyin": pinyin,
            "citation_pinyin": pinyin,
            "context": "isolated",
            "intended": {"id": f"m{i}", "tones": [tone], "labels": ["mai"]},
            "produced_tones": [tone],
        }
        for i, (text, pinyin, tone) in enumerate([("买", "mǎi", "3"), ("卖", "mài", "4")])
    ],
}


def c0_fix_landed() -> bool:
    """True once the contract models take `text_traditional`, the `diag_context` set and
    `diag_minimal` pairs of correct readings (C0's fix round, R74 and R76)."""
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
