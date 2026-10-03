"""tkh deck approve, and the builder applying the approvals (R91). Each test works on a copy of the
sources, so the repository's own approvals.csv stays as it is."""

import json
import tomllib

import pytest
from deck_support import needs_c0_fix, run_deck, copy_sources

from tonekit_harness.deck_build.approvals import read_approvals
from tonekit_harness.deck_build.fingerprint import card_fingerprint

pytestmark = needs_c0_fix

HEADER = "card_id,fingerprint,decision,note\n"


@pytest.fixture
def sources(tmp_path):
    return copy_sources(tmp_path)


def build(capsys, sources, out):
    return run_deck(capsys, "build", "--sources", str(sources), "--out", str(out))


def deck_cards(out):
    return {c["id"]: c for c in json.loads((out / "s05-v1.json").read_text(encoding="utf-8"))["card"]}


def test_the_shipped_approvals_file_is_the_header_and_nothing_else():
    from deck_support import SOURCES

    assert (SOURCES / "approvals.csv").read_text(encoding="utf-8") == HEADER


def test_approving_some_cards_writes_their_current_fingerprints(sources, tmp_path, capsys):
    code, text, err = run_deck(capsys, "approve", "--sources", str(sources), "r01", "g01-c", "g01-e", "r01")
    assert (code, err) == (0, "") and "approved 3 cards in " in text and "run `tkh deck build`" in text
    rows = read_approvals(sources / "approvals.csv")
    assert [(r.card_id, r.decision, r.note) for r in rows] == [
        ("r01", "approved", ""), ("g01-c", "approved", ""), ("g01-e", "approved", ""),
    ]  # fmt: skip
    code, _, _ = build(capsys, sources, tmp_path / "out")
    cards = deck_cards(tmp_path / "out")
    assert code == 0
    assert [i for i, c in cards.items() if c["status"] == "approved"] == ["r01", "g01-c", "g01-e"]
    assert {r.card_id: r.fingerprint for r in rows} == {i: card_fingerprint(cards[i]) for i in ("r01", "g01-c", "g01-e")}


def test_approve_all_covers_every_card_and_the_build_marks_them_in_both_files(sources, tmp_path, capsys):
    code, text, _ = run_deck(capsys, "approve", "--sources", str(sources), "--all", "--note", "DJ audit")
    assert code == 0 and "approved 76 cards" in text
    assert {r.note for r in read_approvals(sources / "approvals.csv")} == {"DJ audit"}
    code, text, _ = build(capsys, sources, tmp_path / "out")
    assert code == 0 and "approvals: 76 of 76 cards approved" in text
    assert {c["status"] for c in deck_cards(tmp_path / "out").values()} == {"approved"}
    toml = tomllib.loads((tmp_path / "out" / "s05-v1.toml").read_text(encoding="utf-8"))
    assert {c["status"] for c in toml["card"]} == {"approved"}
    assert "76 of 76 approved" in (tmp_path / "out" / "s05-v1.audit.md").read_text(encoding="utf-8")


def test_approving_again_updates_the_row_and_the_note(sources, capsys):
    run_deck(capsys, "approve", "--sources", str(sources), "r01", "r02", "--note", "first look")
    run_deck(capsys, "approve", "--sources", str(sources), "r02", "--note", "second look")
    assert [(r.card_id, r.note) for r in read_approvals(sources / "approvals.csv")] == [
        ("r01", "first look"), ("r02", "second look"),
    ]  # fmt: skip


def test_a_card_that_is_not_in_the_deck_is_an_error_and_nothing_is_written(sources, capsys):
    code, text, err = run_deck(capsys, "approve", "--sources", str(sources), "r01", "g99-c", "x1")
    assert code == 1 and text == "" and "not cards of the deck: g99-c, x1" in err
    assert (sources / "approvals.csv").read_text(encoding="utf-8") == HEADER


def test_the_command_wants_card_ids_or_all_and_not_both(sources, capsys):
    for argv in ([], ["--all", "r01"]):
        code, _, err = run_deck(capsys, "approve", "--sources", str(sources), *argv)
        assert code == 1 and "name the cards to approve, or give --all (not both)" in err
    assert (sources / "approvals.csv").read_text(encoding="utf-8") == HEADER


def test_a_rejected_card_is_dropped_by_the_next_build(sources, tmp_path, capsys):
    run_deck(capsys, "approve", "--sources", str(sources), "r08", "--reject", "--note", "too long")
    (row,) = read_approvals(sources / "approvals.csv")
    assert (row.card_id, row.decision, row.note) == ("r08", "rejected", "too long")
    code, text, _ = build(capsys, sources, tmp_path / "out")
    cards = deck_cards(tmp_path / "out")
    assert code == 0 and "r08" not in cards and len(cards) == 75
    assert "  rejected r08 (approvals.csv:2): dropped from the deck" in text


def test_a_rejected_card_can_be_approved_again_because_approve_works_from_the_whole_deck(sources, tmp_path, capsys):
    run_deck(capsys, "approve", "--sources", str(sources), "r08", "--reject")
    run_deck(capsys, "approve", "--sources", str(sources), "r08")
    build(capsys, sources, tmp_path / "out")
    assert deck_cards(tmp_path / "out")["r08"]["status"] == "approved"


def test_approve_all_leaves_a_standing_rejection_alone_and_a_fixed_card_comes_back_into_the_deck(sources, tmp_path, capsys):
    run_deck(capsys, "approve", "--sources", str(sources), "r08", "--reject", "--note", "too long")
    code, text, _ = run_deck(capsys, "approve", "--sources", str(sources), "--all")
    assert code == 0 and "approved 75 cards" in text
    rows = {r.card_id: r for r in read_approvals(sources / "approvals.csv")}
    assert len(rows) == 76 and (rows["r08"].decision, rows["r08"].note) == ("rejected", "too long")
    build(capsys, sources, tmp_path / "out")
    assert "r08" not in deck_cards(tmp_path / "out")
    # the source changes, so the card is no longer the one that was rejected: it is back, unverified
    register = sources / "register.csv"
    register.write_text(register.read_text(encoding="utf-8").replace("short pause", "long pause"), encoding="utf-8")
    _, text, _ = build(capsys, sources, tmp_path / "out")
    assert deck_cards(tmp_path / "out")["r08"]["status"] == "unverified" and "stale rejection r08" in text
    _, text, _ = run_deck(capsys, "approve", "--sources", str(sources), "--all")
    assert "approved 76 cards" in text and {r.decision for r in read_approvals(sources / "approvals.csv")} == {"approved"}


def test_rejecting_one_card_of_a_pair_is_refused_by_the_contract_and_the_message_says_why(sources, tmp_path, capsys):
    run_deck(capsys, "approve", "--sources", str(sources), "g01-e", "--reject")
    code, text, err = build(capsys, sources, tmp_path / "out")
    assert code == 1 and text == "" and not (tmp_path / "out").exists()
    assert "pair 'g01' (set gate) has 1 correct and 0 tone_error cards" in err
    assert "rejected and dropped: g01-e" in err and "reject its partner too" in err


def test_a_card_edited_after_it_was_approved_is_reported_stale_and_stays_unverified(sources, tmp_path, capsys):
    run_deck(capsys, "approve", "--sources", str(sources), "--all")
    register = sources / "register.csv"
    register.write_text(register.read_text(encoding="utf-8").replace("short pause", "long pause"), encoding="utf-8")
    code, text, _ = build(capsys, sources, tmp_path / "out")
    cards = deck_cards(tmp_path / "out")
    assert code == 0 and "approvals: 68 of 76 cards approved" in text
    assert [i for i, c in cards.items() if c["status"] == "unverified"] == [f"r0{n}" for n in range(1, 9)]
    assert text.count("  stale approval r0") == 8 and "the card is now" in text and "it stays unverified" in text
    sheet = (tmp_path / "out" / "s05-v1.audit.md").read_text(encoding="utf-8")
    assert sheet.count("stale approval r0") == 8  # the flag column of the sheet says so too


def test_an_approvals_row_for_a_card_the_deck_lacks_stops_the_build(sources, tmp_path, capsys):
    (sources / "approvals.csv").write_text(HEADER + "g25-c,0123456789ab,approved,\n", encoding="utf-8")
    code, text, err = build(capsys, sources, tmp_path / "out")
    assert code == 1 and text == "" and "approvals.csv:2: g25-c is not a card of the deck (delete the row)" in err


def test_a_sources_folder_without_an_approvals_file_builds_with_nothing_approved(sources, tmp_path, capsys):
    (sources / "approvals.csv").unlink()
    code, text, _ = build(capsys, sources, tmp_path / "out")
    assert code == 0 and "approvals: 0 of 76 cards approved" in text
