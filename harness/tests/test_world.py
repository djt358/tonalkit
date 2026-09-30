"""The WORLD wrapper: analysis on tonekit's frame grid, and resynthesis that keeps the pitch."""

from __future__ import annotations

import numpy as np
import pytest
from support import utterance

from tonekit_harness import synth, world


@pytest.mark.parametrize("extra", [0, 1, 79, 159])
def test_world_analysis_is_on_tonekits_grid(extra):
    pcm = np.concatenate([utterance(["1", "2"]), np.zeros(extra, dtype=np.float32)])
    w = world.analyse(pcm)
    assert len(w.f0) == len(w.sp) == len(w.ap) == len(pcm) // 160 + 1
    assert len(world.synthesise(w, len(pcm))) == len(pcm)
    assert world.synthesise(w).dtype == np.float32


def test_world_resynthesis_keeps_the_pitch(src):
    """Analysing the identity resynthesis again finds the pitch that was given."""
    audio, truth, _ = synth.perturb(src, "identity", {}, 0)
    assert [h is not None for h in truth] == list(src.world.f0 > 0)
    again = world.analyse(audio).f0
    both = (again > 0) & (src.world.f0 > 0)
    assert both.sum() > 50
    off = 12 * np.log2(again[both] / src.world.f0[both])
    assert np.median(np.abs(off)) < 0.5  # semitones
