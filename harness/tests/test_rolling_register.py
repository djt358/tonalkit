"""Registers that follow the speaker (rulings R111, R120): `tkh eval --register-from rolling` (and
`rolling-lite`) grades each clip with the register rolled from the drill and the speaker's earlier
clips only."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import tonekit_py
from support import gate_corpus, make_clip
from test_session_order import recorded, write_session

from tonekit_harness import evaluate, speaker_register
from tonekit_harness.rolling_register import causal_order

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"


@pytest.fixture(scope="module")
def pack_toml() -> str:
    return (PACKS / "cmn.toml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def calib_json() -> str:
    return (PACKS / "cmn.calib.json").read_text(encoding="utf-8")


def test_the_drill_comes_first_then_the_rest_in_reading_order(tmp_path):
    clips = [recorded(tmp_path, "K7Q2MD", c) for c in ["g01-c", "g01-e"]]
    clips.append(recorded(tmp_path, "K7Q2MD", "r01", set="register"))
    write_session(tmp_path, "K7Q2MD", ["g01-e", "r01", "g01-c"])
    assert [c.card for c in causal_order(clips, tmp_path)] == ["r01", "g01-e", "g01-c"]


@pytest.mark.parametrize("register_from", ["rolling", "rolling-lite"])
def test_each_clip_is_graded_with_the_register_of_the_clips_before_it_only(
    tmp_path, pack_toml, calib_json, monkeypatch, register_from
):
    # Two speakers, interleaved in the manifest; each has a drill clip listed last.
    clips = [
        make_clip(tmp_path, f"{who}-{i}", ["4", "1", "3"], speaker=who, seed=i)
        for i in range(3)
        for who in ("ann", "bo")
    ]
    clips += [make_clip(tmp_path, f"{who}-drill", ["1", "2", "3", "4"], set="register", speaker=who)
              for who in ("ann", "bo")]  # fmt: skip
    calls: list[str | None] = []  # the register_json of each analyze call, in order
    real_analyze = tonekit_py.analyze

    def spy(pcm, sample_rate, register_json=None, f0_json=None):
        calls.append(register_json)
        return real_analyze(pcm, sample_rate, register_json, f0_json)

    monkeypatch.setattr(evaluate.tonekit_py, "analyze", spy)
    got = evaluate.run(
        clips, pack_toml, calib_json, None, root=tmp_path, use_cache=False, register_from=register_from
    )

    assert [r.id for r in got] == [c.id for c in clips]  # results in manifest order
    assert len(calls) == len(clips)  # each clip analysed once, with its own register
    # Graded in causal order: ann's drill, ann's phrases, then bo's. The register each is given
    # counts exactly the syllables of the clips before it: never its own, never a later one's.
    counts = [None if r is None else json.loads(r)["n_syllables"] for r in calls]
    assert counts == [None, 4, 7, 10, None, 4, 7, 10]
    by_id = {r.id: r for r in got}
    assert by_id["ann-drill"].register_source == "cold"
    assert all(by_id[f"{w}-{i}"].register_source == "given" for w in ("ann", "bo") for i in range(3))


def test_without_decay_the_rolled_register_is_the_speakers_pool(tmp_path, pack_toml, calib_json):
    # Ruling R107's pooling, which `speaker_register` computes in numpy, to the 0.1 st grid.
    clips = [make_clip(tmp_path, f"c{i}", t, seed=i) for i, t in enumerate([["4", "1", "3"], ["1", "2", "4"]] * 6)]
    grader = evaluate.Grader(pack_toml, calib_json, "cmn-standard", tmp_path, None)
    rolled, frames, syllables = None, [], 0
    for clip in clips:
        analysis = grader.analysis(clip, None)
        _, assessment = grader.assess(clip, analysis)
        rolled = tonekit_py.roll_register(
            rolled, analysis, json.dumps(assessment), pack_toml, calib_json,
            json.dumps({"half_life_s": None, "max_share": None}),
        )  # fmt: skip
        frames += json.loads(analysis)["voiced_st"]
        syllables += 3
    got = json.loads(rolled)["register"]
    want = speaker_register.pooled_register(frames, syllables)
    assert got["n_syllables"] == syllables == want["n_syllables"]
    for key in ("floor_st", "median_st", "ceil_st"):
        assert got[key] == pytest.approx(want[key], abs=0.1), key
    assert np.isfinite([got[k] for k in ("floor_st", "median_st", "ceil_st")]).all()


def test_tkh_eval_reports_the_rolling_parameters(tmp_path, capsys):
    from tonekit_harness import cli

    clips = gate_corpus(tmp_path)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("".join(c.model_dump_json() + "\n" for c in clips), encoding="utf-8")
    report = tmp_path / "report.md"
    code = cli.main([
        "eval", "--manifest", str(manifest), "--pack", str(PACKS / "cmn.toml"), "--report", str(report),
        "--no-cache", "--register-from", "rolling",
    ])  # fmt: skip
    assert code == 0, capsys.readouterr().err
    text = report.read_text(encoding="utf-8")
    assert "earlier clips in reading order, time-weighted (R111)" in text
    assert "half-life 30 s of voiced speech, at most 0.03 of a full pool per clip" in text


def test_without_decay_the_lite_register_is_the_register_update_chain(tmp_path, pack_toml, calib_json):
    # Ruling R120: the lite register with no decay or cap is what the drill chain persists
    # (`register_update`, utterance after utterance from a cold start).
    clips = [make_clip(tmp_path, f"c{i}", t, seed=i) for i, t in enumerate([["4", "1", "3"], ["1", "2", "4"]] * 3)]
    grader = evaluate.Grader(pack_toml, calib_json, "cmn-standard", tmp_path, None)
    lite: str | None = None
    for clip in clips:
        analysis = grader.analysis(clip, lite)
        _, assessment = grader.assess(clip, analysis)
        lite = tonekit_py.roll_register_lite(
            lite, analysis, json.dumps(assessment), pack_toml, calib_json,
            json.dumps({"half_life_s": None, "max_share": None}),
        )  # fmt: skip
        assert json.loads(lite) == assessment["register_update"], clip.id


def test_tkh_eval_reports_the_lite_registers_parameters(tmp_path, capsys):
    from tonekit_harness import cli

    clips = gate_corpus(tmp_path)
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("".join(c.model_dump_json() + "\n" for c in clips), encoding="utf-8")
    report = tmp_path / "report.md"
    code = cli.main([
        "eval", "--manifest", str(manifest), "--pack", str(PACKS / "cmn.toml"), "--report", str(report),
        "--no-cache", "--register-from", "rolling-lite",
    ])  # fmt: skip
    assert code == 0, capsys.readouterr().err
    text = report.read_text(encoding="utf-8")
    assert "time-weighted on the register's four numbers alone (R120)" in text
    assert "half-life 30 s of voiced speech, at most 0.03 of a full pool per clip" in text
