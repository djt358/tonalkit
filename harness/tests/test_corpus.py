"""Writing a synthetic corpus: the WAVs, `manifest.jsonl` and `truth.jsonl`, and that `tkh eval`'s
own loader and grader take the result unchanged."""

from __future__ import annotations

import json

import numpy as np
import pytest

from tonekit_harness import corpus, evaluate, manifest, synth
from tonekit_harness.family import SynthError


def test_rows_round_trip_through_write_and_load_and_the_truth_lines_up(src, tmp_path):
    made = [
        synth.perturb(src, "tone_swap", {"index": 1, "to": "4"}, 0),
        synth.perturb(src, "noise", {"snr_db": 10.0}, 0),
        synth.perturb(src, "rate", {"factor": 1.25}, 0),
    ]
    corpus.write_corpus(tmp_path, made)

    rows = manifest.load(tmp_path / "manifest.jsonl")
    assert rows == [clip for _, _, clip in made]
    truth = [json.loads(line) for line in (tmp_path / "truth.jsonl").read_text().splitlines()]
    assert [t["id"] for t in truth] == [c.id for c in rows]
    for t, (_, f0, _) in zip(truth, made, strict=True):
        assert t["f0_hz"] == f0
        assert any(h is None for h in t["f0_hz"]) and any(h is not None for h in t["f0_hz"])
    for audio, _, clip in made:
        _, back = evaluate.read_wav(tmp_path / clip.path, clip.id)
        np.testing.assert_array_equal(back, audio)


def test_synthetic_rows_are_gradable_by_evaluate_unchanged(src, tmp_path, pack_toml, calib_json):
    made = [synth.perturb(src, "noise", {"snr_db": 20.0}, 0), synth.perturb(src, "identity", {}, 0)]
    corpus.write_corpus(tmp_path, made)
    results = evaluate.run(
        manifest.load(tmp_path / "manifest.jsonl"), pack_toml, calib_json, None,
        root=tmp_path, use_cache=False,
    )  # fmt: skip
    assert [r.set for r in results] == ["synthetic", "synthetic"]
    assert all(r.overall is not None for r in results)


def test_read_truth_gives_each_clips_f0_by_id(src, tmp_path):
    made = [synth.perturb(src, "identity", {}, 0), synth.perturb(src, "noise", {"snr_db": 10.0}, 0)]
    corpus.write_corpus(tmp_path, made)
    truth = corpus.read_truth(tmp_path)
    assert list(truth) == [clip.id for _, _, clip in made]
    for _, f0, clip in made:
        assert truth[clip.id] == f0


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{not json\n", r"truth\.jsonl:1: invalid JSON"),
        ('{"id": "a"}\n', r"truth\.jsonl:1: expected an id and f0_hz"),
        (
            '{"id": "a", "f0_hz": [100.0, null]}\n{"id": "a", "f0_hz": []}\n',
            r"truth\.jsonl:2: duplicate id 'a'",
        ),
    ],
)
def test_read_truth_reports_a_bad_line_with_its_position(tmp_path, text, message):
    (tmp_path / "truth.jsonl").write_text(text, encoding="utf-8")
    with pytest.raises(SynthError, match=message):
        corpus.read_truth(tmp_path)


def test_read_truth_of_a_directory_without_one_is_an_error_naming_it(tmp_path):
    with pytest.raises(SynthError, match=r"no truth\.jsonl in"):
        corpus.read_truth(tmp_path)


@pytest.mark.parametrize(
    "element", ["-3.0", "0", "0.0", '"100"', "true", "NaN", "Infinity", "-Infinity", "[100.0]"]
)
def test_read_truth_wants_every_frame_null_or_a_positive_finite_number(tmp_path, element):
    line = '{"id": "a", "f0_hz": [100.0, ' + element + ", null]}\n"
    (tmp_path / "truth.jsonl").write_text(line, encoding="utf-8")
    message = r"truth\.jsonl:1: f0_hz\[1\] is .*expected null or a positive"
    with pytest.raises(SynthError, match=message):
        corpus.read_truth(tmp_path)


def test_read_truth_accepts_integers_and_nulls(tmp_path):
    (tmp_path / "truth.jsonl").write_text('{"id": "a", "f0_hz": [100, null, 220.5]}\n')
    assert corpus.read_truth(tmp_path) == {"a": [100, None, 220.5]}
