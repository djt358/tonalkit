"""Family parameters: validation, sampling within bounds. No audio: a hand-made `Voice`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tonekit_harness import families
from tonekit_harness.families import PackTones, Voice

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"


@pytest.fixture(scope="module")
def voice() -> Voice:
    """T1 T3, both syllables targetable, on a 20-frame track."""
    st = np.full(40, 15.0)
    pack = PackTones.parse((PACKS / "cmn.toml").read_text(encoding="utf-8"))
    return Voice(
        tones=("1", "3"), extents=((2, 12), (20, 30)), st=st, floor=10.0, ceil=20.0, pack=pack
    )


def draws(voice: Voice, family: str, bounds: dict, n: int = 200) -> dict[str, list[float]]:
    fam = families.get(family)
    resolved = fam.resolve_bounds(bounds)
    rng = np.random.default_rng(0)
    out: dict[str, list[float]] = {name: [] for name in resolved}
    for _ in range(n):
        p = fam.sample(voice, rng, resolved)
        for name in resolved:
            out[name].append(p[name])
    return out


def test_an_unsigned_parameter_with_negative_custom_bounds_is_sampled_inside_them(voice):
    st = draws(voice, "register_shift", {"st": (-6.0, -2.0)})["st"]
    assert all(-6.0 <= x <= -2.0 for x in st)
    assert min(st) < -5.0 and max(st) > -3.0  # spread over the range, not piled up at an end


def test_an_unsigned_parameter_with_bounds_spanning_zero_is_spread_across_them(voice):
    st = np.array(draws(voice, "register_shift", {"st": (-5.0, 1.0)})["st"])
    assert np.all((-5.0 <= st) & (st <= 1.0))
    assert (st < -2).sum() > 40 and (st > -2).sum() > 40  # both halves populated
    assert len(set(st)) > 100  # not a handful of clamped values


def test_a_signed_parameter_is_a_magnitude_with_either_sign(voice):
    ms = np.array(draws(voice, "turn_shift", {"ms": (60.0, 100.0)})["ms"])
    assert np.all((60.0 <= np.abs(ms)) & (np.abs(ms) <= 100.0))
    assert (ms < 0).sum() > 40 and (ms > 0).sum() > 40
