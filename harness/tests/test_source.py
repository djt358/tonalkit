"""Source clips: `prepare` (refusals, syllable spans, the speaker's register) and `load_sources`."""

from __future__ import annotations

import numpy as np
import pytest
from support import RATE, utterance, write_clip
from synth_support import quiet_clip

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
