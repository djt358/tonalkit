"""tkh deck check --ship (R91): a deck ships only when everything is approved and whole."""

from types import SimpleNamespace

import pytest
from deck_support import copy_sources, needs_c0_fix, run_deck

from tonekit_harness.contracts.deck import parse_deck
from tonekit_harness.deck_build import ship_check
from tonekit_harness.deck_build.minimal_set import minimal_cards
from tonekit_harness.deck_build.ship_check import ship_problems


@pytest.fixture
def built(tmp_path, capsys):
    """Build every card of the sources, approve all, and build again: a deck that can ship."""
    sources, out = copy_sources(tmp_path), tmp_path / "out"
    assert run_deck(capsys, "approve", "--sources", str(sources), "--all")[0] == 0
    assert run_deck(capsys, "build", "--sources", str(sources), "--out", str(out))[0] == 0
    return sources, out


@needs_c0_fix
def test_a_deck_with_no_approvals_cannot_ship_and_the_report_says_which_cards(tmp_path, capsys):
    out = tmp_path / "out"
    run_deck(capsys, "build", "--sources", str(copy_sources(tmp_path)), "--out", str(out))
    code, text, err = run_deck(capsys, "check", "--ship", str(out / "s05-v1.json"))
    assert code == 1 and text == ""
    lines = err.splitlines()
    assert lines[0] == f"NOT READY TO SHIP {out / 's05-v1.json'}"
    assert lines[1] == "  76 of 76 cards are not approved: r01, r02, r03, r04, r05, r06, r07, r08, g01-c, g01-e, g02-c, g02-e and 64 more"
    assert lines[-1] == "1 problem"
    # the same deck passes the plain check
    assert run_deck(capsys, "check", str(out / "s05-v1.json"))[0] == 0


@needs_c0_fix
def test_after_approve_all_and_a_build_both_files_can_ship(built, capsys):
    _, out = built
    for name in ("s05-v1.toml", "s05-v1.json"):
        code, text, err = run_deck(capsys, "check", "--ship", str(out / name))
        assert (code, err) == (0, "") and "76 cards, 29 pairs" in text and "status: approved 76" in text
        assert text.rstrip().endswith("ready to ship: every card approved, every pair and set whole")


@needs_c0_fix
def test_a_register_set_under_eight_cards_cannot_ship(tmp_path, capsys):
    sources, out = copy_sources(tmp_path), tmp_path / "out"
    run_deck(capsys, "approve", "--sources", str(sources), "--all")
    run_deck(capsys, "approve", "--sources", str(sources), "r08", "--reject")
    assert run_deck(capsys, "build", "--sources", str(sources), "--out", str(out))[0] == 0
    code, _, err = run_deck(capsys, "check", "--ship", str(out / "s05-v1.toml"))
    assert code == 1 and "  the register set has 7 cards, the kit needs at least 8" in err
    assert "not approved" not in err and err.splitlines()[-1] == "1 problem"


@needs_c0_fix
def test_one_unapproved_card_is_named(tmp_path, capsys):
    sources, out = copy_sources(tmp_path), tmp_path / "out"
    run_deck(capsys, "approve", "--sources", str(sources), "--all")
    register = sources / "register.csv"
    register.write_text(register.read_text(encoding="utf-8").replace("short pause", "long pause"), encoding="utf-8")
    run_deck(capsys, "build", "--sources", str(sources), "--out", str(out))
    _, _, err = run_deck(capsys, "check", "--ship", str(out / "s05-v1.json"))
    assert "  8 of 76 cards are not approved: r01, r02, r03, r04, r05, r06, r07, r08" in err


def deck_of(tmp_path, csv_text):
    path = tmp_path / "m.csv"
    path.write_text(csv_text, encoding="utf-8")
    cards, _ = minimal_cards(path)
    return cards


@needs_c0_fix
def test_a_minimal_set_that_does_not_list_all_its_words_is_not_whole(tmp_path):
    cards = deck_of(tmp_path, "group,text,pinyin\nm01,水,shuǐ\nm01,睡,shuì\nm01,谁,shuí\n")
    for c in cards:
        c["status"] = "approved"
    cards[0]["distractors"] = cards[0]["distractors"][:1]  # 水 names 睡 only: the contract accepts that
    deck = parse_deck({"deck": {"id": "t", "lect": "cmn", "version": 1, "title": "t"}, "card": cards})
    problems = [p for p in ship_problems(deck) if "minimal set" in p]
    assert problems == ["minimal set m01 is not whole: m01-a does not list shui2 as a distractor"]


def fake(set_, pair, label):
    return SimpleNamespace(set=set_, pair=pair, label=label)


def test_a_pair_that_is_not_one_correct_and_one_error_is_not_whole():
    cards = [fake("gate", "g01", "correct"), fake("gate", "g02", "correct"), fake("gate", "g02", "tone_error")]
    assert ship_check._pair_problems(cards) == [  # the contract refuses this deck at load; ship says it too
        "pair g01 of gate is not whole: it has correct, not one correct and one tone_error"
    ]
    assert ship_check._pair_problems([fake("diag_minimal", None, "correct"), fake("register", None, "correct")]) == []


def test_a_minimal_set_of_one_word_is_not_whole():
    one = SimpleNamespace(
        set="diag_minimal", pair="m01", id="m01-a", intended=SimpleNamespace(id="mai3"), distractors=[]
    )
    assert ship_check._minimal_problems([one]) == ["minimal set m01 is not whole: it has one word, a set needs two or more"]


def test_a_long_list_of_cards_is_cut_after_twelve():
    assert ship_check._ids([f"c{i}" for i in range(12)]).endswith("c11")
    assert ship_check._ids([f"c{i}" for i in range(15)]).endswith("c11 and 3 more")
