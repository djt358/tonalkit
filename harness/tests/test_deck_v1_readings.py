"""The committed deck against the contract's reading rules (pinyin, tones, sandhi, one-tone errors).
Unlike test_deck_v1.py this reads the TOML as plain data and asks `deck_build.trial` to run each card
through the contract, so it holds on a contract model that has not got C0's fix round yet."""

import tomllib

import pytest
from deck_support import DECK_DIR

from tonekit_harness.deck_build import trial


@pytest.fixture(scope="module")
def cards() -> list[dict]:
    return tomllib.loads((DECK_DIR / "s05-v1.toml").read_text(encoding="utf-8"))["card"]


def test_every_card_reads_as_its_pinyin_tones_and_sandhi_say(cards):
    assert len(cards) == 76
    bad = {c["id"]: trial.reading_problems(c) for c in cards if trial.reading_problems(c)}
    assert bad == {}


def test_every_gate_and_t23_pair_is_one_correct_card_and_one_single_tone_error(cards):
    for set_ in ("gate", "diag_t23"):
        pairs = [c for c in cards if c["set"] == set_]
        assert len(pairs) == {"gate": 40, "diag_t23": 8}[set_]
        assert trial.problems(pairs) == []
