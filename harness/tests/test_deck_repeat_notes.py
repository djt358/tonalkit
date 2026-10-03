"""Repeated cards (the register block) number their notes, so eight identical cards in a row don't
look like the kit is stuck."""

import json

from deck_support import DECK_DIR

from tonekit_harness.deck_build.single_cards import repeat_note


def test_a_single_card_keeps_its_note():
    assert repeat_note("Four sounds.", 1, 1) == "Four sounds."
    assert repeat_note(None, 1, 1) is None


def test_the_first_repeat_says_how_many_and_the_rest_count():
    assert repeat_note("Four sounds.", 1, 8) == "Four sounds. You'll read this card 8 times in a row."
    assert repeat_note("Four sounds.", 3, 8) == "Again, 3 of 8. Four sounds."
    assert repeat_note(None, 2, 8) == "Again, 2 of 8."


def test_every_register_card_in_v1_has_a_distinct_note():
    cards = json.loads((DECK_DIR / "s05-v1.json").read_text())["card"]
    notes = [c["prompt_note"] for c in cards if c["set"] == "register"]
    assert len(notes) == 8 and len(set(notes)) == 8
    assert notes[0].endswith("8 times in a row.") and notes[7].startswith("Again, 8 of 8.")
