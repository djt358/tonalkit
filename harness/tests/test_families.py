"""Family parameters: validation, sampling within bounds. No audio: a hand-made `Voice`."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tonekit_harness import families, graded
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


# ---- the turning point of a tone with more than three knots --------------------------------------


@pytest.mark.parametrize(
    ("knots", "index"),
    [
        ((2.0, 1.0, 4.0), 1),  # T3: the dip
        ((3.0, 1.0, 2.0, 4.0), 1),  # a low, then a rise: the low is the turn, not the middle
        ((1.0, 4.0, 3.0, 2.0), 1),  # rises to a high, then falls
        ((4.0, 3.0, 5.0, 2.0), 2),  # the peak, though the first interior knot is a shallower dip
        ((1.0, 2.0, 3.0, 4.0), 2),  # no interior extremum: the middle knot, as for three knots
        ((1.0, 3.0, 5.0), 1),
    ],
)
def test_the_turning_knot_is_the_interior_extremum(knots, index):
    assert graded.turning_knot(knots) == index


def test_turn_shift_moves_the_turning_point_of_a_four_knot_contour():
    """A made-up tone that falls to a low at its second knot and then rises: shifting the turn by
    +-80 ms moves that low, not the third knot."""
    pack = PackTones("xx", {"a": (3.0, 1.0, 2.0, 4.0)})
    voice = Voice(
        tones=("a",), extents=((5, 45),), st=np.full(60, 15.0), floor=10.0, ceil=20.0, pack=pack
    )
    fam = families.get("turn_shift")
    low = {}
    for ms in (-80.0, 80.0):
        contour = fam.contour(voice, fam.validate(voice, {"index": 0, "ms": ms}))
        low[ms] = int(np.nanargmin(contour[5:45]))
        assert contour[5:45][low[ms]] == pytest.approx(10.0)  # Chao 1, the floor: the same low
    assert (low[80.0] - low[-80.0]) * 10 == pytest.approx(160, abs=20)  # frames of 10 ms


# ---- drawing a family ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def plain_voice() -> Voice:
    """T1 T2: the only tone error that applies is `tone_swap` (no T3 to flatten, no neutral)."""
    pack = PackTones.parse((PACKS / "cmn.toml").read_text(encoding="utf-8"))
    return Voice(
        tones=("1", "2"), extents=((2, 12), (20, 30)), st=np.full(40, 15.0), floor=10.0, ceil=20.0,
        pack=pack,
    )  # fmt: skip


def class_shares(voice: Voice, labels: tuple[str, ...], n: int = 2000) -> dict[str, float]:
    pool = families.searched(labels)
    bounds = families.resolve_pool_bounds(pool, None)
    rng = np.random.default_rng(0)
    drawn = [families.draw(voice, rng, pool, bounds)[0].label for _ in range(n)]
    return {label: drawn.count(label) / n for label in labels}


def test_draw_picks_the_class_first_so_each_class_is_equally_likely(plain_voice):
    """With few tone errors applicable, a family-uniform draw would give tone errors 1 in 4; the
    class comes first, so they get half."""
    shares = class_shares(plain_voice, ("tone_error", "correct"))
    assert shares["tone_error"] == pytest.approx(0.5, abs=0.05)
    assert shares["correct"] == pytest.approx(0.5, abs=0.05)
    three = class_shares(plain_voice, ("tone_error", "graded", "correct"))
    assert all(share == pytest.approx(1 / 3, abs=0.05) for share in three.values())


def test_draw_skips_a_class_with_no_applicable_family(voice):
    pack = voice.pack
    nothing_targetable = Voice(
        tones=("1", "3"), extents=(None, None), st=np.full(40, 15.0), floor=10.0, ceil=20.0,
        pack=pack,
    )  # fmt: skip
    assert class_shares(nothing_targetable, ("tone_error", "correct")) == {
        "tone_error": 0.0,
        "correct": 1.0,
    }
    tone_errors = families.searched(("tone_error",))
    bounds = families.resolve_pool_bounds(tone_errors, None)
    with pytest.raises(families.SynthError, match="no family can perturb this source"):
        families.draw(nothing_targetable, np.random.default_rng(0), tone_errors, bounds)


def test_draw_gives_the_noise_recording_to_the_noise_family_only(voice):
    pool = families.searched(("correct",))
    bounds = families.resolve_pool_bounds(pool, None)
    rng = np.random.default_rng(0)
    paths = {"noise_wav": "bed.wav"}
    drawn = [families.draw(voice, rng, pool, bounds, paths) for _ in range(60)]
    noisy = {family.name: params for family, params in drawn if family.name == "noise"}
    assert noisy["noise"]["noise_wav"] == "bed.wav"
    assert all("noise_wav" not in p for f, p in drawn if f.name != "noise")
    assert all(f.validate(voice, p) for f, p in drawn)  # every draw is valid as it stands
