"""Rows joined to the deck: one per kept clip, with the card's set, label, readings and context."""

from __future__ import annotations

import json

import pytest
from intake_support import CARDS, DECK_JSON, kit_session

from tonekit_harness.contracts.bundle import Session
from tonekit_harness.contracts.deck import parse_deck
from tonekit_harness.intake.conditions import KIT_CONDITION
from tonekit_harness.intake.errors import IntakeError
from tonekit_harness.intake.rows import join_session

DECK = parse_deck(json.loads(DECK_JSON.read_text(encoding="utf-8")))


def join(cards, skipped=(), source="volunteer-corpus", deck=DECK):
    session = Session.model_validate(kit_session("K7Q2MD", cards, list(skipped)))
    return join_session(session, deck, source=source, path_of=lambda card: f"audio/K7Q2MD/{card}.wav")


def test_each_kept_clip_is_one_row_joined_to_its_card():
    joined = join(["g01-c", "g01-e", "r01", "m01-a", "x02"])
    rows = {r.card: r for r in joined.rows}
    assert set(rows) == {"g01-c", "g01-e", "r01", "m01-a", "x02"}
    for card, row in rows.items():
        deck_card = CARDS[card]
        assert row.id == f"K7Q2MD-{card}" and row.path == f"audio/K7Q2MD/{card}.wav"
        assert row.speaker == "v-k7q2md" and row.deck == "s05-v1"
        assert (row.set, row.label, row.context) == (deck_card["set"], deck_card["label"], deck_card["context"])
        assert row.produced_tones == deck_card["produced_tones"]
        assert row.intended.model_dump() == deck_card["intended"]
        assert [d.model_dump() for d in row.distractors] == deck_card["distractors"]
        assert row.condition == KIT_CONDITION and row.needs_listen is False and row.synthetic is None


def test_the_error_card_carries_its_erroneous_produced_tones():
    row = next(r for r in join(["g01-c", "g01-e"]).rows if r.card == "g01-e")
    assert row.label == "tone_error"
    assert row.produced_tones == ["4", "1", "4"] and row.intended.tones == ["4", "1", "3"]


def test_pairs_are_scoped_to_the_session_and_unpaired_cards_have_none():
    rows = {r.card: r for r in join(["g01-c", "g01-e", "m01-a", "r01"]).rows}
    assert rows["g01-c"].pair == rows["g01-e"].pair == "K7Q2MD-g01"
    assert rows["m01-a"].pair == "K7Q2MD-m01"
    assert rows["r01"].pair is None


def test_the_take_count_is_the_sessions():
    session = kit_session("K7Q2MD", ["r01", "r02", "r03"])
    rows = join(["r01", "r02", "r03"]).rows
    assert [r.take for r in rows] == [c["takes"] for c in session["clips"]]


def test_every_row_has_the_corpus_source():
    assert {r.source for r in join(["r01", "x01"], source="dj-corpus").rows} == {"dj-corpus"}


def test_skipped_cards_get_no_row_and_rows_follow_deck_order():
    joined = join(["x01", "r02", "r01"], skipped=["r03"])
    assert [r.card for r in joined.rows] == ["r01", "r02", "x01"]
    assert joined.kept_out == {}


def test_a_pair_card_whose_twin_was_not_recorded_is_kept_out():
    joined = join(["g01-c", "g02-e", "g02-c", "t01-c"], skipped=["g01-e"])
    assert [r.card for r in joined.rows] == ["g02-c", "g02-e"]
    assert joined.kept_out == {
        "g01-c": "its gate twin g01-e was not recorded",
        "t01-c": "its diag_t23 twin t01-e was not recorded",
    }


def test_a_minimal_set_member_alone_is_kept():
    assert [r.card for r in join(["m01-a"]).rows] == ["m01-a"]


def test_a_card_the_deck_does_not_have_is_refused():
    with pytest.raises(IntakeError, match="does not have: zz-1"):
        join(["r01"], skipped=["zz-1"])


def test_an_unapproved_card_is_refused():
    data = json.loads(DECK_JSON.read_text(encoding="utf-8"))
    for card in data["card"]:
        if card["id"] == "r01":
            card["status"] = "unverified"
    with pytest.raises(IntakeError, match="not approved.*r01"):
        join(["r01"], deck=parse_deck(data))
