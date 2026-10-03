"""Helpers for the deck builder tests."""

from __future__ import annotations

import shutil

import pytest

from tonekit_harness.contracts.deck import DeckError, parse_deck
from tonekit_harness.contracts.lects import lect_rules
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


# what C0's fix rounds add to the contract (R74, R76, R81, R88): a diag_context card, a traditional
# text and note, and a diag_minimal group of correct words that name each other as distractors
_PROBE = {
    "deck": {"id": "probe", "lect": "cmn", "version": 1, "title": "probe"},
    "card": [
        _probe_card(
            "p1", "diag_context", "水", "shuǐ", "3", text_traditional="水", prompt_note="x", prompt_note_traditional="x"
        ),
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
    """True once the contract models take `text_traditional`, `prompt_note_traditional`, the
    `diag_context` set and `diag_minimal` groups of correct readings that name each other as
    distractors, and a citation 3-3 has the one native reading 2-3 (C0's fix rounds: R74, R76, R81,
    R88, R89)."""
    try:
        parse_deck(_PROBE)
    except DeckError:
        return False
    return lect_rules("cmn").surface_options(["3", "3"], ["a", "b"], "phrase") == {("2", "3")}


needs_c0_fix = pytest.mark.skipif(
    not c0_fix_landed(),
    reason="needs C0's fix rounds (traditional text and note, diag_context, diag_minimal pairs, R89); merge s05/c0",
)


def run_deck(capsys, *argv) -> tuple[int, str, str]:
    """`tkh deck ARGV...`: the exit code, what it printed and what it complained about."""
    from tonekit_harness import cli

    code = cli.main(["deck", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def copy_sources(tmp_path):
    """A copy of kit/deck/sources to build from and approve in without touching the repository."""
    out = tmp_path / "sources"
    shutil.copytree(SOURCES, out)
    return out


def gate_row(text: str, citation: str, spoken: str, trad: str | None = None, where: str = "t.csv:2") -> GateRow:
    return GateRow(where, Reading(text, citation, spoken, "phrase", trad))


def small_deck_data(pairs: int = 2) -> dict:
    """A deck of the first gate pairs of the stand-in and one register card (the stand-in's twenty
    are built, so the gate quotas hold, and the first `pairs` pairs kept). Needs C0's fix (R89)."""
    from tonekit_harness.deck_build.cards import candidate, make_card
    from tonekit_harness.deck_build.gate import build_gate, standin_rows
    from tonekit_harness.deck_build.lexicon import load_lexicon
    from tonekit_harness.deck_build.reading import Reading

    gate = build_gate(standin_rows(SOURCES / "gate_standin.csv"), load_lexicon(SOURCES / "tone_variants.csv"), 20)
    gate.cards = gate.cards[: 2 * pairs]
    register = make_card(
        id="r01", set="register", label="correct", reading=Reading("妈麻马骂", "mā má mǎ mà", "mā má mǎ mà", "isolated", "媽麻馬罵"),
        intended=candidate("r01", "mā má mǎ mà"), note="Pause.",
    )  # fmt: skip
    meta = {"id": "t-v1", "lect": "cmn", "version": 1, "title": "Test deck"}
    return {"deck": meta, "card": [register, *gate.cards]}
