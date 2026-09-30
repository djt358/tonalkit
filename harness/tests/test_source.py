"""Source clips: `prepare` (refusals, syllable spans, the speaker's register) and `load_sources`."""

from __future__ import annotations

import inspect
import json

import numpy as np
import pytest
from support import RATE, candidate, utterance, write_clip, write_manifest
from synth_support import PACKS, quiet_clip

from tonekit_harness import evaluate, source
from tonekit_harness.family import SynthError


def test_the_register_is_the_voiced_p5_to_p95(src):
    voiced = 12 * np.log2(src.world.f0[src.world.f0 > 0] / 55.0)
    p5, p95 = np.percentile(voiced, [5, 95])
    assert (src.voice.floor, src.voice.ceil) == pytest.approx((p5, p95))
    assert src.voice.ceil - src.voice.floor > 4.0  # the support voice spans an octave


def test_a_narrow_register_is_widened_symmetrically_to_4_st():
    level = np.full(50, 20.0)
    assert source.register_bounds(level) == pytest.approx((18.0, 22.0))
    assert source.register_bounds(np.linspace(19.0, 21.0, 50)) == pytest.approx((18.0, 22.0))
    wide = np.linspace(10.0, 20.0, 101)
    assert source.register_bounds(wide) == pytest.approx((10.5, 19.5))  # p5 and p95, untouched


def test_sources_that_would_be_mislabelled_are_refused(root, pack_toml):
    synthetic = quiet_clip(root, "already-synthetic", ["1", "2"], set="synthetic")
    with pytest.raises(SynthError, match="already-synthetic.*synthetic"):
        source.prepare(synthetic, root=root, pack_toml=pack_toml)
    wrong = quiet_clip(root, "wrong-tones", ["1", "2"], label="tone_error")
    with pytest.raises(SynthError, match="wrong-tones.*tone_error.*correct"):
        source.prepare(wrong, root=root, pack_toml=pack_toml)


def test_a_clip_with_nothing_to_target_is_refused_naming_it(root, pack_toml):
    silence = write_clip(root, "silent", np.zeros(RATE, dtype=np.float32), intended=["1"])
    with pytest.raises(SynthError, match="silent.*no syllable"):
        source.prepare(silence, root=root, pack_toml=pack_toml)


def test_a_missing_wav_is_an_eval_error_naming_the_clip(root, pack_toml):
    ghost = quiet_clip(root, "ghost", ["1"])
    (root / ghost.path).unlink()
    with pytest.raises(evaluate.EvalError, match="ghost.*cannot read"):
        source.prepare(ghost, root=root, pack_toml=pack_toml)


def test_an_intended_tone_the_pack_lacks_is_refused(root, pack_toml):
    odd = write_clip(root, "odd-tone", 0.5 * utterance(["1", "2"]), intended=["1", "9"])
    with pytest.raises(SynthError, match="odd-tone.*tone '9' is not in the pack"):
        source.prepare(odd, root=root, pack_toml=pack_toml)


def test_prepare_finds_a_span_for_each_syllable_and_uses_the_pack_accent(src, pack_toml):
    assert src.voice.tones == ("4", "1", "3")
    assert all(extent is not None for extent in src.voice.extents)
    starts = [e[0] for e in src.voice.extents]
    assert starts == sorted(starts)
    assert src.accent == "cmn-standard" == evaluate.base_accent(pack_toml)
    for start, end in src.voice.extents:
        assert end - start >= 5 and np.isfinite(src.voice.st[start:end]).sum() >= 5


# ---- the voiced core -----------------------------------------------------------------------------


def mask(n: int, *runs: tuple[int, int]) -> np.ndarray:
    voiced = np.zeros(n, dtype=bool)
    for start, end in runs:
        voiced[start:end] = True
    return voiced


def test_the_core_is_the_longest_run_not_the_first_to_the_last_voiced_frame():
    # stray voiced frames at both edges of the span, a 2-frame dropout inside the core
    stray = mask(40, (1, 2), (10, 16), (18, 26), (38, 39))
    assert source.voiced_core(stray) == (10, 26)
    # a 3-frame gap separates runs; the run with more voiced frames wins, and the first on a tie
    assert source.voiced_core(mask(40, (5, 11), (14, 30))) == (14, 30)
    assert source.voiced_core(mask(40, (5, 12), (15, 22))) == (5, 12)


def test_the_core_needs_min_voiced_frames_in_the_run_itself():
    n = source.MIN_VOICED_FRAMES
    assert source.voiced_core(mask(30, (10, 10 + n))) == (10, 10 + n)
    assert source.voiced_core(mask(30, (10, 10 + n - 1))) is None
    # many frames in total, but never `n` in one run: no core
    scattered = mask(60, *[(i, i + n - 1) for i in range(0, 60, n + 3)])
    assert scattered.sum() >= n and source.voiced_core(scattered) is None
    assert source.voiced_core(mask(30)) is None


def test_a_stray_voiced_frame_at_a_span_edge_does_not_stretch_the_extent(src, monkeypatch):
    """Through `_extents`: tonekit's span is 0..60, the voiced frames are a stray one at 2, the
    syllable at 20..40 and a stray one at 57."""
    voiced = mask(60, (2, 3), (20, 40), (57, 58))
    frames = [{"hz": 150.0 if v else None} for v in voiced]
    analysis = json.dumps({"f0": {"frames": frames}})
    decoded = json.dumps(
        {"candidates": [{"syllables": [{"span": {"start_frame": 0, "end_frame": 60}}]}]}
    )
    monkeypatch.setattr(source.evaluate, "analyze_pcm", lambda *args: analysis)
    monkeypatch.setattr(source.tonekit_py, "decode", lambda *args: decoded)
    clip = src.clip.model_copy(update={"intended": candidate(["1"])})

    extents = source._extents(clip, src.pcm, voiced, "", None, "cmn-standard", None)
    assert extents == [(20, 40)]


# ---- load_sources --------------------------------------------------------------------------------


def test_load_sources_yields_one_prepared_source_at_a_time(tmp_path, monkeypatch):
    clips = [quiet_clip(tmp_path, f"gen-{i}", ["4", "1", "3"]) for i in range(2)]
    manifest_path = write_manifest(tmp_path / "manifest.jsonl", clips)
    prepared = []
    real_prepare = source.prepare

    def counting(clip, **kw):
        prepared.append(clip.id)
        return real_prepare(clip, **kw)

    monkeypatch.setattr(source, "prepare", counting)
    sources = source.load_sources(manifest_path, PACKS / "cmn.toml", None, None)

    assert inspect.isgenerator(sources) and prepared == []  # nothing is analysed up front
    assert next(sources).clip.id == "gen-0" and prepared == ["gen-0"]
    assert [s.clip.id for s in sources] == ["gen-1"] and prepared == ["gen-0", "gen-1"]


def test_load_sources_collects_what_it_skipped_and_fails_when_nothing_is_usable(tmp_path, capsys):
    good = quiet_clip(tmp_path, "good", ["4", "1", "3"])
    silent = write_clip(tmp_path, "silent", np.zeros(RATE, dtype=np.float32), intended=["1"])
    both = write_manifest(tmp_path / "both.jsonl", [silent, good])
    skipped: list[str] = []

    loaded = list(source.load_sources(both, PACKS / "cmn.toml", None, None, skipped=skipped))
    assert [s.clip.id for s in loaded] == ["good"]
    assert len(skipped) == 1 and skipped[0].startswith("silent:")
    assert f"warning: skipping {skipped[0]}" in capsys.readouterr().err

    only = write_manifest(tmp_path / "only.jsonl", [silent])
    with pytest.raises(SynthError, match="no clip labelled 'correct' can be perturbed"):
        list(source.load_sources(only, PACKS / "cmn.toml", None, None))
