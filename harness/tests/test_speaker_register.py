"""Registers from a speaker's other clips (ruling R107): `speaker_register` and
`tkh eval --register-from speaker`."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import tonekit_py
from support import gate_corpus, make_clip

from tonekit_harness import evaluate, speaker_register
from tonekit_harness.evaluate import EvalError

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"


@pytest.fixture(scope="module")
def pack_toml() -> str:
    return (PACKS / "cmn.toml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def calib_json() -> str:
    return (PACKS / "cmn.calib.json").read_text(encoding="utf-8")


def test_a_pooled_register_is_the_p5_p50_p95_of_the_voiced_semitones():
    st = np.linspace(10.0, 30.0, 201)
    got = speaker_register.pooled_register(list(st), syllables=7)
    assert got == pytest.approx({"floor_st": 11.0, "median_st": 20.0, "ceil_st": 29.0, "n_syllables": 7})


def test_a_narrow_pooled_register_is_widened_symmetrically_to_4_st_and_nan_is_ignored():
    got = speaker_register.pooled_register([20.0, 20.5, 21.0, float("nan")], syllables=1)
    assert got["ceil_st"] - got["floor_st"] == pytest.approx(4.0)
    assert (got["floor_st"] + got["ceil_st"]) / 2 == pytest.approx(20.5)
    assert speaker_register.pooled_register([float("nan")], syllables=3) is None
    assert speaker_register.pooled_register([], syllables=0) is None


def _clip(cid: str, speaker: str) -> SimpleNamespace:
    return SimpleNamespace(id=cid, speaker=speaker)  # all a register needs of a clip


def test_each_clip_gets_the_register_of_its_speakers_other_clips_only():
    clips = [_clip("a1", "a"), _clip("a2", "a"), _clip("a3", "a"), _clip("b1", "b")]
    level = {"a1": 10.0, "a2": 20.0, "a3": 30.0, "b1": 15.0}
    analyses = {c.id: {"voiced_st": [level[c.id]] * 50, "nuclei": [{}] * 2} for c in clips}
    seen: list[str] = []

    def analysis_of(c) -> dict:
        seen.append(c.id)
        return analyses[c.id]

    got = speaker_register.leave_one_out_registers(clips, analysis_of)

    assert sorted(seen) == sorted(c.id for c in clips)  # each clip analysed once
    a1 = json.loads(got["a1"])  # a2 and a3: 20 and 30 st, never a1's own 10
    assert a1["median_st"] == pytest.approx(25.0) and a1["n_syllables"] == 4
    assert a1["floor_st"] > 20.0 - 1e-9 and a1["ceil_st"] < 30.0 + 1e-9
    assert json.loads(got["a3"])["median_st"] == pytest.approx(15.0)
    assert got["b1"] is None  # b's only clip: nothing else to learn from


def test_eval_with_registers_from_the_speaker_gives_each_clip_a_register_from_the_others(
    tmp_path, pack_toml, calib_json, monkeypatch
):
    clips = gate_corpus(tmp_path)
    alone = make_clip(tmp_path, "gate-03-correct", ["1", "1", "1"], pair="gate-03", speaker="ann")
    registers: list[str | None] = []  # the register_json of each analyze call
    real_analyze = tonekit_py.analyze

    def spy(pcm, sample_rate, register_json=None, f0_json=None):
        registers.append(register_json)
        return real_analyze(pcm, sample_rate, register_json, f0_json)

    monkeypatch.setattr(evaluate.tonekit_py, "analyze", spy)
    got = evaluate.run(
        [*clips, alone], pack_toml, calib_json, None, root=tmp_path, cache_dir=tmp_path / "c",
        register_from="speaker",
    )  # fmt: skip

    by_id = {r.id: r for r in got}
    assert [r.id for r in got] == [c.id for c in [*clips, alone]]
    assert all(by_id[c.id].register_source == "given" for c in clips)  # dj has four clips
    assert by_id["gate-03-correct"].register_source == "cold"  # ann has one
    given = [json.loads(r) for r in registers if r is not None]
    assert len(given) == len(clips)
    assert all(g["n_syllables"] > 0 for g in given)


def test_an_unknown_register_source_is_an_eval_error(tmp_path, pack_toml, calib_json):
    clips = gate_corpus(tmp_path)
    with pytest.raises(EvalError, match="unknown register source 'drills'.*drill, speaker"):
        evaluate.run(clips, pack_toml, calib_json, None, root=tmp_path, register_from="drills")
