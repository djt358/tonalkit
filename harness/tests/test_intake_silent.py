"""Silent takes: a clip that is all zeros, or peaks below -60 dBFS, gets no row and no audio, intake
names it, and its pair twin becomes a half pair (the kit refuses such takes now; older bundles have them)."""

from __future__ import annotations

import json

import pytest
from bundle_support import wav_bytes
from intake_support import DECK_JSON, SMALL, entries, kit_bundle, kit_session, options, tkh, tree

from tonekit_harness import manifest
from tonekit_harness.contracts.bundle import Session, read_bundle
from tonekit_harness.contracts.deck import parse_deck
from tonekit_harness.intake.errors import IntakeError
from tonekit_harness.intake.rows import join_session
from tonekit_harness.intake.run import intake_bundle
from tonekit_harness.intake.silence import SILENT_PEAK_DBFS, is_silent, silent_cards

CORPUS = "corpora/volunteers-s05-v1"
DECK = parse_deck(json.loads(DECK_JSON.read_text(encoding="utf-8")))
# -60 dBFS is 32.77 of 32768: a peak of 32 is under the line, 33 is over it.
UNDER, OVER = 32, 33


def test_all_zeros_and_peaks_under_minus_60_dbfs_are_silent_and_nothing_else():
    assert SILENT_PEAK_DBFS == -60.0
    assert is_silent(wav_bytes(level=0))
    assert is_silent(wav_bytes(level=UNDER)) and is_silent(wav_bytes(level=-UNDER))
    assert not is_silent(wav_bytes(level=OVER)) and not is_silent(wav_bytes(level=-OVER))
    assert not is_silent(wav_bytes(level=-32768))  # full scale, negative: no overflow in the peak


def test_one_loud_enough_sample_in_a_clip_of_zeros_makes_it_audible():
    data = bytearray(wav_bytes(frames=1600, level=0))
    data[44 + 2 * 800 : 44 + 2 * 800 + 2] = OVER.to_bytes(2, "little", signed=True)
    assert not is_silent(bytes(data))


def test_the_silent_cards_of_a_bundle_in_session_order(tmp_path):
    bundle = read_bundle(kit_bundle(tmp_path / "in", levels={"r01": UNDER, "g01-e": 0, "m01-a": OVER}))
    assert silent_cards(bundle) == ["g01-e", "r01"]
    assert silent_cards(read_bundle(kit_bundle(tmp_path / "ok", "ABCDEF"))) == []


def join(cards, silent, skipped=()):
    session = Session.model_validate(kit_session("K7Q2MD", cards, list(skipped)))
    return join_session(
        session, DECK, source="volunteer-corpus", path_of=lambda card: f"audio/K7Q2MD/{card}.wav", silent=silent
    )


def test_a_silent_card_gets_no_row_and_is_named_not_kept_out():
    joined = join(["r01", "r02", "x01"], silent={"r02"})
    assert [r.card for r in joined.rows] == ["r01", "x01"]
    assert joined.silent == ["r02"] and joined.kept_out == {}


def test_the_twin_of_a_silent_gate_card_is_a_half_pair_and_is_left_out_too():
    joined = join(["g01-c", "g01-e", "g02-c", "g02-e", "t01-c", "t01-e"], silent={"g01-e", "t01-c"})
    assert [r.card for r in joined.rows] == ["g02-c", "g02-e"]
    assert joined.silent == ["g01-e", "t01-c"]  # deck order
    assert joined.kept_out == {
        "g01-c": "its gate twin g01-e is a silent take",
        "t01-e": "its diag_t23 twin t01-c is a silent take",
    }


def test_both_cards_of_a_pair_silent_leave_two_silent_takes_and_no_half_pair():
    joined = join(["g01-c", "g01-e", "r01"], silent={"g01-c", "g01-e"})
    assert [r.card for r in joined.rows] == ["r01"]
    assert joined.silent == ["g01-c", "g01-e"] and joined.kept_out == {}


def test_a_silent_card_that_was_not_recorded_changes_nothing():
    joined = join(["r01"], silent={"g01-e"}, skipped=["g01-e"])
    assert [r.card for r in joined.rows] == ["r01"] and joined.silent == []


def test_a_silent_clip_is_left_out_of_the_corpus_with_its_twin(tmp_path):
    root = tmp_path / "data"
    bundle = kit_bundle(tmp_path / "in", levels={"g01-e": 0, "r01": UNDER})
    result = intake_bundle(bundle, options(root))
    kept = ["g02-c", "g02-e", "m01-a"]
    files = tree(root)
    assert set(files) == {f"{CORPUS}/audio/K7Q2MD/{c}.wav" for c in kept} | {
        f"{CORPUS}/{n}" for n in ("corpus.toml", "manifest.jsonl", "sessions/K7Q2MD.json")
    }
    assert [c.card for c in manifest.load(result.manifest)] == kept
    assert files[f"{CORPUS}/sessions/K7Q2MD.json"] == read_bundle(bundle).session_bytes()  # the bundle's own record
    assert result.silent == ["r01", "g01-e"] and result.kept_out == {"g01-c": "its gate twin g01-e is a silent take"}
    assert result.per_set == {"gate": 2, "diag_minimal": 1}


def test_a_quiet_but_audible_clip_is_kept(tmp_path):
    # -50 dBFS (peak 104): the kit flags such a take as quiet but keeps it, and so does intake.
    result = intake_bundle(kit_bundle(tmp_path / "in", levels={"r01": 104}), options(tmp_path / "data"))
    assert result.silent == [] and "r01" in {c.card for c in manifest.load(result.manifest)}


def test_a_session_of_silent_takes_only_is_refused_and_writes_nothing(tmp_path):
    root = tmp_path / "data"
    bundle = kit_bundle(tmp_path / "in", levels=dict.fromkeys(SMALL, 0))
    with pytest.raises(IntakeError, match="no clip to keep .*silent"):
        intake_bundle(bundle, options(root))
    assert entries(root) == []


def test_the_summary_names_each_silent_take_and_the_half_pair_it_leaves(tmp_path, capsys):
    bundle = kit_bundle(tmp_path / "in", levels={"g01-e": 0, "r01": UNDER})
    code, out, err = tkh(capsys, "intake", str(bundle), "--data", str(tmp_path / "data"))
    assert code == 0 and err == ""
    assert "clips kept: 3 (gate 2, diag_minimal 1)" in out
    assert "silent take: r01 (no row, no audio)" in out
    assert "silent take: g01-e (no row, no audio)" in out
    assert "kept out: 1 recorded card, no row and no audio" in out
    assert "g01-c: its gate twin g01-e is a silent take" in out


def test_a_bundle_without_silent_takes_prints_no_silent_line(tmp_path, capsys):
    _, out, _ = tkh(capsys, "intake", str(kit_bundle(tmp_path / "in")), "--data", str(tmp_path / "data"))
    assert "silent take" not in out and "is a silent take" not in out
