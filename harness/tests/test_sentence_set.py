"""Ruling R121: a public corpus's sentence is one correct reading (intended = produced), never a deck
card and never in a gate; `tkh eval` grades a corpus of them without a verdict and reports how
tonekit heard their syllables, and `tkh relabel` keeps a sentence one correct reading."""

from __future__ import annotations

import pytest
from intake_support import tkh
from pydantic import ValidationError
from support import make_clip, write_manifest
from test_manifest import row

from tonekit_harness import metrics, report
from tonekit_harness.clearance import Clearance
from tonekit_harness.contracts.deck import Card
from tonekit_harness.contracts.gate import Select
from tonekit_harness.contracts.relabel import Decision
from tonekit_harness.evaluate import Result, Syllable
from tonekit_harness.manifest import Clip
from tonekit_harness.relabel.rules import relabelled

TONES = ["4", "1", "3", "2"]


def sentence(**overrides) -> dict:
    base = row(
        id="SSB00050001",
        path="audio/SSB0005/SSB00050001.wav",
        speaker="SSB0005",
        set="sentence",
        pair=None,
        label="correct",
        intended={"id": "SSB00050001", "tones": TONES, "labels": ["yi", "bei", "shui", "ne"]},
        distractors=[],
        produced_tones=TONES,
        source="aishell-3",
        context="phrase",
    )
    base.update(overrides)
    return base


# ---- the manifest row ------------------------------------------------------------------------


def test_a_sentence_row_validates():
    clip = Clip.model_validate(sentence())
    assert (clip.set, clip.label, clip.pair, clip.produced_tones) == ("sentence", "correct", None, TONES)


@pytest.mark.parametrize(
    "overrides,complaint",
    [
        ({"label": "tone_error"}, "a sentence is 'correct'"),
        ({"produced_tones": ["4", "1", "3", "4"]}, "must equal its intended tones"),
        ({"produced_tones": None}, "must equal its intended tones"),
        ({"pair": "p1"}, "sentences are not paired"),
    ],
)
def test_a_sentence_is_one_correct_unpaired_reading(overrides, complaint):
    with pytest.raises(ValidationError, match=complaint):
        Clip.model_validate(sentence(**overrides))


def test_a_sentence_is_not_a_deck_set_and_no_gate_can_select_it():
    with pytest.raises(ValidationError):
        Select.model_validate({"corpora": ["*"], "kinds": ["public"], "splits": ["calib"], "sets": ["sentence"]})
    assert "sentence" not in Card.model_json_schema()["properties"]["set"]["enum"]


# ---- relabel ---------------------------------------------------------------------------------


def test_a_sentence_heard_otherwise_takes_the_heard_tones_as_its_reading():
    original = Clip.model_validate(sentence())
    heard = ["2", "1", "3", "2"]
    decision = Decision(clip=original.id, verdict="heard", tones=heard, decided_at="2026-10-15T10:00:00Z")
    after = relabelled(original, decision)
    assert after is not None
    assert (after.label, after.produced_tones, after.intended.tones) == ("correct", heard, heard)
    Clip.model_validate(after.model_dump())  # still a valid sentence row


# ---- metrics and the report ------------------------------------------------------------------


def result(cid: str, heard: list[str | None], overall: float | None, set_: str = "sentence") -> Result:
    syllables = [
        Syllable(expected=e, heard=h, p_correct=0.5, distance=1.0, measured="Full") for e, h in zip(TONES, heard)
    ]
    return Result(cid, set_, None, "correct", "s1", overall, 1, 1.0, syllables, "cold")


def test_sentence_accuracy_counts_heard_syllables_heard_as_the_transcript():
    results = [
        result("a", ["4", "1", "3", "2"], 0.8),
        result("b", ["4", "2", None, "2"], None),
        result("m", TONES, 0.9, "diag_minimal"),
    ]
    found = metrics.sentence_accuracy(results)
    assert found == metrics.SentenceAccuracy(clips=2, unscored=1, syllables=8, heard=7, agreed=6)
    assert found.accuracy == pytest.approx(6 / 7)
    assert metrics.sentence_accuracy([result("m", TONES, 0.9, "diag_minimal")]) is None


def test_sentences_are_never_failures_and_need_no_gate():
    results = [result("a", ["1", "1", "1", "1"], 0.1)]
    assert not metrics.has_gate_clips(results)
    assert metrics.failures(results, None, None) == []
    assert metrics.count_robustness(results, None) is None


def test_a_report_without_gate_clips_has_no_verdict_and_shows_the_sentence_diagnostic(tmp_path):
    out = tmp_path / "r.md"
    sentences = metrics.sentence_accuracy([result("a", ["4", "1", "3", "1"], 0.8)])
    report.write(out, None, None, None, [], clearance=Clearance("gate"), sentences=sentences)
    text = out.read_text(encoding="utf-8")
    assert "**No S1 verdict**" in text and "PASS" not in text and "FAIL" not in text
    assert "| Sentence tone accuracy (sentence; heard syllables) | 0.750 (3/4) |" in text
    assert "## Gate pairs" not in text


# ---- tkh eval over a corpus of sentences -----------------------------------------------------


def test_tkh_eval_grades_a_corpus_of_sentences_without_a_verdict(tmp_path, capsys):
    clips = [
        make_clip(tmp_path, f"s{i}", tones, set="sentence", speaker="spk", seed=i, source="aishell-3")
        for i, tones in enumerate([["4", "1", "3"], ["1", "2", "4", "1"]])
    ]
    manifest = write_manifest(tmp_path / "manifest.jsonl", clips)
    report_path = tmp_path / "report.md"
    code, out, err = tkh(
        capsys, "eval", "--manifest", str(manifest), "--pack", "../packs/cmn/cmn.toml",
        "--report", str(report_path), "--no-cache", "--register-from", "speaker",
    )  # fmt: skip
    assert code == 0, err
    assert out.startswith("S1: no verdict (no gate clips), sentence tone accuracy ")
    text = report_path.read_text(encoding="utf-8")
    assert "**No S1 verdict**" in text and "- clips: sentence 2" in text
    assert "Sentences with no score" in text
