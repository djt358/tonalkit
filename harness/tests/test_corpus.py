"""Writing a synthetic corpus: the WAVs, `manifest.jsonl` and `truth.jsonl`, and that `tkh eval`'s
own loader and grader take the result unchanged."""

from __future__ import annotations

import json

import numpy as np

from tonekit_harness import corpus, evaluate, manifest, synth


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
