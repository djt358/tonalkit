"""`tkh relabel`'s rules on a small synthetic volunteer corpus: each verdict, pairs kept whole,
the log, the stale marker, refusals that write nothing, and idempotence."""

from __future__ import annotations

import pytest
from intake_support import tree
from relabel_support import (
    CODE,
    CORPUS,
    corpus_dir,
    decision,
    export,
    log_entries,
    log_lines,
    make_corpus,
    manifest_file,
    relabel,
    rows,
)

from tonekit_harness.contracts.registry import StaleMarker
from tonekit_harness.contracts.relabel import Decision, RelabelError
from tonekit_harness.relabel import apply

G1C, G1E, G2C, G2E = (f"{CODE}-{c}" for c in ("g01-c", "g01-e", "g02-c", "g02-e"))
T1C, T1E, R01, M01 = (f"{CODE}-{c}" for c in ("t01-c", "t01-e", "r01", "m01-a"))
LATER = "2026-10-07T13:00:00Z"


@pytest.fixture
def root(tmp_path):
    return make_corpus(tmp_path)


def stale_reasons(root) -> list[str]:
    path = root / "stale" / f"{CORPUS}.json"
    return [r.reason for r in StaleMarker.model_validate_json(path.read_text()).reasons] if path.exists() else []


# ---- the rules -------------------------------------------------------------------------------


def test_a_clip_read_as_the_card_says_keeps_its_row_and_only_the_decision_is_logged(root):
    before = manifest_file(root).read_bytes()
    outcome = relabel(root, decision(G1E, "as_card", ["4", "1", "4"]), decision(G1C, "as_card"))
    assert manifest_file(root).read_bytes() == before
    assert outcome.plan.changes == {} and stale_reasons(root) == []
    assert [(e.clip, e.decision.verdict, e.row) for e in log_entries(root)] == [
        (G1E, "as_card", None), (G1C, "as_card", None)
    ]  # fmt: skip


def test_an_error_card_read_as_the_correct_word_becomes_correct_and_its_pair_a_half_pair(root):
    relabel(root, decision(G1E, "heard", ["4", "1", "3"]))
    after = rows(root)
    assert (after[G1E].label, after[G1E].produced_tones) == ("correct", ["4", "1", "3"])
    # two correct readings are no pair: both leave it (out of the gate's pairs), both rows stay
    assert after[G1E].pair is None and after[G1C].pair is None
    assert after[G1C].label == "correct" and after[G1C].produced_tones == ["4", "1", "3"]
    assert after[G2C].pair == after[G2E].pair == f"{CODE}-g02"


def test_a_correct_card_read_with_one_wrong_tone_becomes_tone_error(root):
    relabel(root, decision(G2C, "heard", ["4", "2", "1"]))
    after = rows(root)
    assert (after[G2C].label, after[G2C].produced_tones) == ("tone_error", ["4", "2", "1"])
    assert after[G2C].intended.tones == ["4", "3", "1"]  # what the card means stays
    assert after[G2C].pair is None and after[G2E].pair is None  # two error readings: a half pair


def test_a_correct_card_read_with_two_wrong_tones_is_tone_error_too(root):
    relabel(root, decision(M01, "heard", ["4"]), decision(R01, "heard", ["1", "2", "2", "2"]))
    after = rows(root)
    assert (after[R01].label, after[R01].produced_tones) == ("tone_error", ["1", "2", "2", "2"])
    # a minimal-set clip is no pair-set member: its group id stays
    assert (after[M01].label, after[M01].pair) == ("tone_error", f"{CODE}-m01")


def test_a_pair_read_the_other_way_round_stays_a_pair(root):
    relabel(root, decision(T1C, "heard", ["4", "2"]), decision(T1E, "heard", ["4", "3"]))
    after = rows(root)
    assert (after[T1C].label, after[T1E].label) == ("tone_error", "correct")
    assert after[T1C].pair == after[T1E].pair == f"{CODE}-t01"


def test_an_error_card_read_with_another_error_stays_tone_error_in_its_pair(root):
    relabel(root, decision(G1E, "heard", ["4", "2", "3"]))
    after = rows(root)
    assert (after[G1E].label, after[G1E].produced_tones, after[G1E].pair) == (
        "tone_error", ["4", "2", "3"], f"{CODE}-g01"
    )  # fmt: skip


def test_heard_with_the_cards_own_tones_is_as_the_card_says(root):
    before = manifest_file(root).read_bytes()
    relabel(root, decision(G1E, "heard", ["4", "1", "4"]))
    assert manifest_file(root).read_bytes() == before
    assert log_entries(root)[0].decision.verdict == "as_card"


def test_unclear_keeps_the_label_and_flags_the_clip_for_another_listen(root):
    relabel(root, decision(G1E, "unclear"))
    after = rows(root)
    assert (after[G1E].label, after[G1E].needs_listen, after[G1E].pair) == ("tone_error", True, f"{CODE}-g01")


def test_exclude_removes_the_row_keeps_the_audio_and_breaks_the_pair(root):
    relabel(root, decision(G2E, "exclude"))
    after = rows(root)
    assert G2E not in after and after[G2C].pair is None
    assert (corpus_dir(root) / "audio" / CODE / "g02-e.wav").is_file()


def test_rows_not_relabelled_stay_byte_for_byte(root):
    lines = manifest_file(root).read_text().splitlines()
    relabel(root, decision(G1E, "heard", ["4", "1", "3"]))
    new = manifest_file(root).read_text().splitlines()
    untouched = [i for i, line in enumerate(lines) if G1E not in line and G1C not in line]
    assert [new[i] for i in untouched] == [lines[i] for i in untouched]


# ---- the log and the stale marker -------------------------------------------------------------


def test_the_log_keeps_each_decision_and_each_row_before_and_after(root):
    original = rows(root)[G1E]
    relabel(root, decision(G1E, "heard", ["4", "1", "3"]))
    entries = {e.clip: e for e in log_entries(root)}
    assert set(entries) == {G1E, G1C}
    e = entries[G1E]
    assert (e.session, e.decision.who, e.decision.tones) == (CODE, "DJ", ["4", "1", "3"])
    assert e.row.before == original and e.row.after == rows(root)[G1E]
    twin = entries[G1C]  # changed because of its twin: a row change and no decision of its own
    assert twin.decision is None and twin.row.before.pair == f"{CODE}-g01" and twin.row.after.pair is None


def test_a_relabel_that_changes_rows_marks_the_corpus_stale(root):
    outcome = relabel(root, decision(G1E, "heard", ["4", "1", "3"]))
    assert stale_reasons(root) == ["relabelled 2 clips (relabels-test.json)"]
    assert outcome.stale == root / "stale" / f"{CORPUS}.json"
    assert G1E not in (root / "stale" / f"{CORPUS}.json").read_text()


# ---- idempotence and later exports -------------------------------------------------------------


def test_applying_the_same_file_twice_changes_nothing_the_second_time(root):
    decisions = (decision(G1E, "heard", ["4", "1", "3"]), decision(G2E, "exclude"), decision(R01, "unclear"))
    relabel(root, *decisions)
    files = tree(root)
    again = relabel(root, *decisions)
    assert again.plan.nothing and tree(root) == files


def test_a_newer_decision_replaces_the_earlier_one_and_restores_the_pair(root):
    original = manifest_file(root).read_bytes()
    relabel(root, decision(G1E, "heard", ["4", "1", "3"]))
    relabel(root, decision(G1E, "as_card", at=LATER))
    assert manifest_file(root).read_bytes() == original  # the row intake wrote, its pair whole
    assert [e.decision.verdict for e in log_entries(root) if e.decision] == ["heard", "as_card"]


def test_an_excluded_clip_comes_back_when_a_newer_decision_keeps_it(root):
    original = rows(root)
    relabel(root, decision(G2E, "exclude"))
    relabel(root, decision(G2E, "heard", ["4", "3", "1"], at=LATER))
    after = rows(root)
    assert after[G2E].label == "correct" and after[G2E].produced_tones == ["4", "3", "1"]
    assert after[G2E].pair is None and after[G2C].pair is None  # two correct readings
    assert set(after) == set(original)


def test_an_older_decision_does_not_undo_a_newer_one(root):
    relabel(root, decision(G1E, "heard", ["4", "1", "3"], at=LATER))
    files = tree(root)
    outcome = relabel(root, decision(G1E, "as_card"))
    assert outcome.plan.older == [G1E] and tree(root) == files


def test_a_relabel_after_an_earlier_one_starts_from_the_row_intake_wrote(root):
    relabel(root, decision(G1E, "heard", ["4", "1", "3"]))
    relabel(root, decision(G1E, "heard", ["4", "2", "4"], at=LATER))
    after = rows(root)
    # a tone_error again, in its pair again: not built on the earlier relabel's row
    assert (after[G1E].label, after[G1E].produced_tones, after[G1E].pair) == (
        "tone_error", ["4", "2", "4"], f"{CODE}-g01"
    )  # fmt: skip
    assert after[G1C].pair == f"{CODE}-g01"


def test_decisions_for_clips_the_corpus_does_not_have_are_skipped(root):
    outcome = relabel(root, decision("ABCDEF-g01-e", "exclude"), decision(G1E, "unclear"))
    assert outcome.plan.unknown == ["ABCDEF-g01-e"] and rows(root)[G1E].needs_listen


def test_a_run_cut_after_the_log_is_finished_by_running_it_again(root, monkeypatch):
    def cut(*_):
        raise KeyboardInterrupt

    monkeypatch.setattr(apply.os, "replace", cut)
    with pytest.raises(KeyboardInterrupt):
        relabel(root, decision(G1E, "heard", ["4", "1", "3"]))
    monkeypatch.undo()
    assert rows(root)[G1E].label == "tone_error"  # the manifest is as it was
    assert not list(corpus_dir(root).glob(".*relabel*"))  # and the new one is not left behind
    relabel(root, decision(G1E, "heard", ["4", "1", "3"]))
    assert rows(root)[G1E].label == "correct" and rows(root)[G1C].pair is None


# ---- refusals ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (decision(G1E, "heard", ["4", "1"]), "2 tones for a reading of 3 syllables"),
        (decision(G1E, "heard", ["4", "1", "6"]), "tones 6 are not tone ids"),
        (decision(G1E, "as_card", ["4", "1", "3"]), "the card asks for 4 1 4"),
    ],
)
def test_a_decision_that_does_not_fit_its_clip_refuses_the_file_and_writes_nothing(root, bad, message):
    files = tree(root)
    with pytest.raises(RelabelError, match=message):
        relabel(root, decision(G2E, "exclude"), bad)
    assert tree(root) == files


def test_a_file_for_another_corpus_is_refused(root):
    files = tree(root)
    with pytest.raises(RelabelError, match="for corpus 'other'"):
        relabel(root, decision(G1E, "exclude"), corpus="other")
    assert tree(root) == files


def test_a_corpus_that_does_not_exist_is_refused(tmp_path):
    with pytest.raises(RelabelError, match="no corpus"):
        relabel(tmp_path / "data", decision(G1E, "exclude"))


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"verdict": "heard", "tones": None}, "needs the tones heard"),
        ({"verdict": "exclude", "tones": ["4", "1", "3"]}, "takes no tones"),
    ],
)
def test_a_verdict_and_its_tones_must_agree(data, message):
    with pytest.raises(ValueError, match=message):
        Decision.model_validate({**decision(G1E, "heard"), **data})


def test_an_export_decides_each_clip_once():
    with pytest.raises(ValueError, match="more than once"):
        export(decision(G1E, "exclude"), decision(G1E, "unclear"))


def test_a_new_manifest_a_killed_relabel_left_behind_is_removed_by_the_next(root):
    stray = corpus_dir(root) / ".manifest.jsonl.relabel-99999"
    stray.write_text("{}\n")
    relabel(root, decision(G1E, "exclude"))
    assert not stray.exists()


def test_log_lines_are_plain_json_with_the_session_code(root):
    relabel(root, decision(G1E, "exclude"))
    assert {line["session"] for line in log_lines(root)} == {CODE}
