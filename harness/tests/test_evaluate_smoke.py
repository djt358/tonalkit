"""`evaluate.run` end to end on a few synthetic clips: shapes, register handling, the analysis
cache and input errors. What the scores say about tone correctness is Task 16's business; these
tests only need the pipeline to produce well-formed results."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest
import tonekit_py
from scipy.io import wavfile
from support import RATE, gate_corpus, make_clip

from tonekit_harness import evaluate, manifest, metrics, report
from tonekit_harness.evaluate import EvalError, Result

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"


@pytest.fixture(scope="module")
def pack_toml() -> str:
    return (PACKS / "cmn.toml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def calib_json() -> str:
    return (PACKS / "cmn.calib.json").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def corpus(tmp_path_factory) -> tuple[Path, list[manifest.Clip]]:
    root = tmp_path_factory.mktemp("corpus")
    return root, gate_corpus(root)


@pytest.fixture(scope="module")
def results(corpus, pack_toml, calib_json, tmp_path_factory) -> list[Result]:
    root, clips = corpus
    return evaluate.run(
        clips, pack_toml, calib_json, None, root=root, cache_dir=tmp_path_factory.mktemp("cache")
    )


def test_run_returns_one_result_per_clip_in_manifest_order(corpus, results):
    _, clips = corpus
    assert [r.id for r in results] == [c.id for c in clips]
    for clip, r in zip(clips, results, strict=True):
        assert isinstance(r, Result)
        assert (r.set, r.pair, r.label, r.speaker) == (
            clip.set, clip.pair, clip.label, clip.speaker
        )  # fmt: skip
        assert r.register_source == "cold"  # no register clips in this manifest


def test_each_result_has_a_syllable_per_intended_tone_with_the_right_shapes(corpus, results):
    _, clips = corpus
    for clip, r in zip(clips, results, strict=True):
        assert isinstance(r.intended_rank, int) and r.intended_rank >= 1
        assert isinstance(r.margin_llr, float) and math.isfinite(r.margin_llr)
        assert r.overall is None or 0.0 <= r.overall <= 1.0
        assert [s.expected for s in r.syllables] == clip.intended.tones
        for s in r.syllables:
            assert isinstance(s.p_correct, float) and 0.0 <= s.p_correct <= 1.0
            assert s.distance is None or isinstance(s.distance, float)
            assert s.heard is None or s.heard in {"1", "2", "3", "4", "5"}
            assert s.measured in {"Full", "Partial", "NotMeasured"}
            for kind, amount in s.deltas:
                assert isinstance(kind, str) and isinstance(amount, float)
        assert all(isinstance(issue, str) for issue in r.issues)


def test_the_synthetic_correct_clips_are_measured(results):
    """The generator is good enough that tonekit finds the syllables (an all-NotMeasured result
    would make every shape test above vacuous)."""
    correct = [r for r in results if r.label == "correct"]
    assert [r.overall is not None for r in correct] == [True, True]
    assert all(s.measured != "NotMeasured" for r in correct for s in r.syllables)


def test_results_feed_the_gate_and_the_report(results, tmp_path):
    gate = metrics.loo_gate(results)
    assert set(gate.thresholds) == {"gate-01", "gate-02"}
    assert len(gate.outcomes) == 2
    theta = gate.median_threshold
    out = tmp_path / "reports" / "gate.md"
    report.write(
        out,
        gate,
        metrics.candidate_id_accuracy(results),
        metrics.count_robustness(results, theta),
        metrics.failures(results, gate, theta),
    )
    text = out.read_text(encoding="utf-8")
    assert f"S1: {'PASS' if gate.passed else 'FAIL'}" in text
    assert "gate-01" in text and "gate-02" in text


def test_the_request_names_the_accent_and_distractors(
    corpus, pack_toml, calib_json, tmp_path, monkeypatch
):
    root, _ = corpus
    clip = make_clip(
        root, "min-1", ["4", "1", "3"], set="diag_minimal", label="correct",
        distractors=[["4", "2", "3"], ["4", "3", "3"]],
    )  # fmt: skip

    requests: list[dict] = []  # the request of each assess call
    real_assess = tonekit_py.assess

    def spy(analysis_json, pack, calib, request_json):
        requests.append(json.loads(request_json))
        return real_assess(analysis_json, pack, calib, request_json)

    monkeypatch.setattr(evaluate.tonekit_py, "assess", spy)
    (result,) = evaluate.run([clip], pack_toml, calib_json, "cmn-TW", root=root, cache_dir=tmp_path)

    (request,) = requests
    assert request["grading"]["accent"] == "cmn-TW"
    assert request["intended"]["id"] == "4-1-3"
    assert [d["id"] for d in request["distractors"]] == ["4-2-3", "4-3-3"]
    assert [[t["tone"] for t in d["targets"]] for d in request["distractors"]] == [
        ["4", "2", "3"],
        ["4", "3", "3"],
    ]
    assert 1 <= result.intended_rank <= 3  # ranked among the intended reading and its 2 distractors


def test_an_unknown_accent_is_an_error_naming_the_clip(corpus, pack_toml, calib_json, tmp_path):
    root, clips = corpus
    with pytest.raises(EvalError, match="gate-01-correct.*accent"):
        evaluate.run(clips[:1], pack_toml, calib_json, "cmn-nowhere", root=root, cache_dir=tmp_path)


def test_the_default_accent_is_the_packs_base_accent(corpus, pack_toml, calib_json, tmp_path):
    root, clips = corpus
    base = evaluate.run(clips[:1], pack_toml, calib_json, None, root=root, cache_dir=tmp_path)
    explicit = evaluate.run(
        clips[:1], pack_toml, calib_json, "cmn-standard", root=root, cache_dir=tmp_path
    )
    assert base == explicit


def test_calib_is_optional(corpus, pack_toml, tmp_path):
    root, clips = corpus
    (result,) = evaluate.run(clips[:1], pack_toml, None, None, root=root, cache_dir=tmp_path)
    assert result.id == "gate-01-correct"


# ---- register ----------------------------------------------------------------------------------


def test_register_clips_give_the_speakers_other_clips_a_given_register(
    corpus, pack_toml, calib_json, tmp_path, monkeypatch
):
    root, clips = corpus
    register = [
        make_clip(
            root, f"register-{i}", ["1", "2", "3", "4"], set="register", label="n/a", speaker="dj",
            seed=10 + i,
        )
        for i in (1, 2)
    ]  # fmt: skip
    other = make_clip(root, "gate-03-correct", ["1", "1", "1"], pair="gate-03", speaker="ann")
    mixed = [clips[0], *register, other]  # the register clips are not first in the manifest

    registers: list[str | None] = []  # the register_json of each analyze call, in call order
    real_analyze = tonekit_py.analyze

    def spy(pcm, sample_rate, register_json=None, f0_json=None):
        registers.append(register_json)
        return real_analyze(pcm, sample_rate, register_json, f0_json)

    monkeypatch.setattr(evaluate.tonekit_py, "analyze", spy)
    got = evaluate.run(mixed, pack_toml, calib_json, None, root=root, cache_dir=tmp_path)
    by_id = {r.id: r for r in got}

    # The first register clip is analysed cold, the second with the register learnt from the
    # first; dj's other clips get the register after both; ann has none and stays cold.
    assert [r.id for r in got] == [c.id for c in mixed]
    assert by_id["register-1"].register_source == "cold"
    assert by_id["register-2"].register_source == "given"
    assert by_id["gate-01-correct"].register_source == "given"
    assert by_id["gate-03-correct"].register_source == "cold"

    # analyze ran register-1, register-2, then dj's gate clip, then ann's (manifest order for the
    # non-register clips).
    assert registers[0] is None and registers[3] is None
    after_one, after_two = json.loads(registers[1]), json.loads(registers[2])
    assert set(after_two) == {"floor_st", "median_st", "ceil_st", "n_syllables"}
    assert 0 < after_one["n_syllables"] < after_two["n_syllables"]


def test_speaker_registers_chains_each_speakers_register_clips(corpus, pack_toml, calib_json):
    root, clips = corpus
    register = [
        make_clip(
            root, f"register-{i}", ["1", "2", "3", "4"], set="register", label="n/a", speaker="dj",
            seed=10 + i,
        )
        for i in (1, 2)
    ]  # fmt: skip
    other = make_clip(root, "gate-03-correct", ["1", "1", "1"], pair="gate-03", speaker="ann")
    grader = evaluate.Grader(pack_toml, calib_json, "cmn-standard", root=root, cache_dir=None)

    registers = evaluate.speaker_registers([clips[0], *register, other], grader)

    assert list(registers) == ["dj", "ann"]
    assert json.loads(registers["dj"])["n_syllables"] > 0
    assert registers["ann"] is None  # no register clips: analysed cold


# ---- cache -------------------------------------------------------------------------------------


def test_analyses_are_cached_by_content_and_reused(
    corpus, pack_toml, calib_json, tmp_path, monkeypatch
):
    root, clips = corpus
    first = evaluate.run(clips, pack_toml, calib_json, None, root=root, cache_dir=tmp_path)
    cached = sorted(tmp_path.glob("*.json"))
    assert len(cached) == len(clips)
    assert all(len(p.stem) == 64 for p in cached)  # a sha256 hex digest
    assert isinstance(json.loads(cached[0].read_text(encoding="utf-8")), dict)

    def boom(*args, **kwargs):
        raise AssertionError("analyze called although the analysis is cached")

    monkeypatch.setattr(evaluate.tonekit_py, "analyze", boom)
    again = evaluate.run(clips, pack_toml, calib_json, None, root=root, cache_dir=tmp_path)
    assert again == first


def test_the_cache_key_follows_the_audio_not_the_clip_id(pack_toml, calib_json, tmp_path):
    cache = tmp_path / "cache"
    first = make_clip(tmp_path / "a", "same-id", ["4", "1", "3"], seed=1)
    second = make_clip(tmp_path / "b", "same-id", ["4", "1", "3"], seed=2)
    again = make_clip(tmp_path / "c", "other-id", ["4", "1", "3"], seed=1)  # same audio as `first`
    for root, clip in (("a", first), ("b", second), ("c", again)):
        evaluate.run([clip], pack_toml, calib_json, None, root=tmp_path / root, cache_dir=cache)
    assert len(list(cache.glob("*.json"))) == 2  # a and c share an entry; b's audio differs


def test_no_cache_neither_reads_nor_writes(corpus, pack_toml, calib_json, tmp_path):
    root, clips = corpus
    cache = tmp_path / "cache"
    evaluate.run(
        clips[:1], pack_toml, calib_json, None, root=root, cache_dir=cache, use_cache=False
    )
    assert not cache.exists()


def test_a_corrupt_cache_entry_is_recomputed(corpus, pack_toml, calib_json, tmp_path):
    root, clips = corpus
    want = evaluate.run(clips[:1], pack_toml, calib_json, None, root=root, cache_dir=tmp_path)
    (entry,) = tmp_path.glob("*.json")
    entry.write_text("{not json", encoding="utf-8")
    got = evaluate.run(clips[:1], pack_toml, calib_json, None, root=root, cache_dir=tmp_path)
    assert got == want
    assert isinstance(json.loads(entry.read_text(encoding="utf-8")), dict)


# ---- input errors ----------------------------------------------------------------------------


def test_a_missing_wav_is_an_error_naming_the_clip(corpus, pack_toml, calib_json, tmp_path):
    root, clips = corpus
    ghost = clips[0].model_copy(update={"id": "ghost", "path": "no/such.wav"})
    with pytest.raises(EvalError, match="ghost.*no/such.wav"):
        evaluate.run([ghost], pack_toml, calib_json, None, root=root, cache_dir=tmp_path)


def test_only_16k_mono_wavs_are_accepted(corpus, pack_toml, calib_json, tmp_path):
    root, clips = corpus
    tone = np.sin(2 * np.pi * 150 * np.arange(8_000) / 8_000).astype(np.float32)
    wavfile.write(root / "rate8k.wav", 8_000, tone)
    wavfile.write(root / "stereo.wav", RATE, np.stack([tone, tone], axis=1))
    for name, why in (("rate8k", "8000 Hz"), ("stereo", "mono")):
        clip = clips[0].model_copy(update={"id": name, "path": f"{name}.wav"})
        with pytest.raises(EvalError, match=f"{name}.*{why}.*tkh ingest"):
            evaluate.run([clip], pack_toml, calib_json, None, root=root, cache_dir=tmp_path)


@pytest.mark.parametrize(
    ("name", "cut", "why"),
    [
        ("one-sample-short", -4, "Reached EOF prematurely"),  # scipy only warns, and drops a sample
        ("mid-sample", -2, "buffer size"),
        ("mid-header", 30, "unpack"),
    ],
)
def test_a_truncated_wav_is_an_error_naming_the_clip(
    corpus, pack_toml, calib_json, tmp_path, name, cut, why
):
    root, clips = corpus
    whole = (root / clips[0].path).read_bytes()
    (root / f"{name}.wav").write_bytes(whole[:cut])
    clip = clips[0].model_copy(update={"id": name, "path": f"{name}.wav"})
    with pytest.raises(EvalError, match=f"{name}.*not a readable WAV file.*{why}"):
        evaluate.run([clip], pack_toml, calib_json, None, root=root, cache_dir=tmp_path)


def test_a_wav_with_an_unknown_chunk_is_still_read(corpus, pack_toml, calib_json, tmp_path):
    """scipy warns "Chunk (non-data) not understood" for chunks it skips; that is harmless."""
    root, clips = corpus
    whole = (root / clips[0].path).read_bytes()
    extra = b"abcd" + (6).to_bytes(4, "little") + b"noise!"
    body = whole[8:] + extra
    (root / "extra-chunk.wav").write_bytes(b"RIFF" + len(body).to_bytes(4, "little") + body)
    clip = clips[0].model_copy(update={"id": "extra-chunk", "path": "extra-chunk.wav"})
    (result,) = evaluate.run([clip], pack_toml, calib_json, None, root=root, cache_dir=tmp_path)
    (plain,) = evaluate.run(clips[:1], pack_toml, calib_json, None, root=root, cache_dir=tmp_path)
    assert result.overall == plain.overall


def test_duplicate_clip_ids_are_an_error(corpus, pack_toml, calib_json, tmp_path):
    root, clips = corpus
    with pytest.raises(EvalError, match="duplicate clip id 'gate-01-correct'"):
        evaluate.run(
            [clips[0], clips[0]], pack_toml, calib_json, None, root=root, cache_dir=tmp_path
        )


def test_a_pack_without_a_base_accent_needs_an_explicit_accent(corpus, calib_json, tmp_path):
    root, clips = corpus
    with pytest.raises(EvalError, match="base_accent"):
        evaluate.run(
            clips[:1], "[pack]\nlect = 'cmn'\n", calib_json, None, root=root, cache_dir=tmp_path
        )
