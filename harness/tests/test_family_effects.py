"""What each perturbation family does to a real source, read off the ground-truth f0 that `perturb`
reports (exactly the f0 handed to WORLD), and the bounds and validation every family enforces.
The families' sampling logic, on a hand-made voice, is in test_families.py."""

from __future__ import annotations

import json

import numpy as np
import pytest
from synth_support import HOP, core, semitones

from tonekit_harness import synth
from tonekit_harness.family import SynthError


def test_unvoiced_frames_stay_none_in_the_truth(src):
    _, truth, _ = synth.perturb(src, "tone_swap", {"index": 1, "to": "2"}, 0)
    assert [h is None for h in truth] == list(src.world.f0 == 0)


def test_tone_swap_of_a_level_syllable_to_4_falls_over_the_syllable(src):
    _, truth, row = synth.perturb(src, "tone_swap", {"index": 1, "to": "4"}, 1)
    _, identity, _ = synth.perturb(src, "identity", {}, 1)

    fall = core(src, truth, 1)
    assert row.label == "tone_error"
    assert fall[0] - fall[-1] > 6.0  # a T4 falls most of the register
    assert np.all(np.diff(fall) <= 1e-9)  # and falls all the way
    level = core(src, identity, 1)
    assert abs(level[0] - level[-1]) < 1.5  # the source syllable it replaced was level


def test_register_shift_moves_the_voiced_truth_by_the_given_semitones(src):
    _, shifted, _ = synth.perturb(src, "register_shift", {"st": 3.0}, 0)
    _, identity, _ = synth.perturb(src, "identity", {}, 0)
    assert [h is None for h in shifted] == [h is None for h in identity]
    diff = semitones(shifted) - semitones(identity)
    assert np.nanmax(np.abs(diff - 3.0)) < 1e-6


def test_range_compress_narrows_the_range_about_the_midline(src):
    _, squeezed, _ = synth.perturb(src, "range_compress", {"factor": 0.5}, 0)
    _, identity, _ = synth.perturb(src, "identity", {}, 0)
    mid = (src.voice.floor + src.voice.ceil) / 2
    assert np.nanmax(np.abs(semitones(squeezed) - (mid + 0.5 * (semitones(identity) - mid)))) < 1e-6


def test_t3_no_dip_renders_a_low_rise_where_the_source_dips(src):
    _, truth, row = synth.perturb(src, "t3_no_dip", {"index": 2}, 0)
    rise = core(src, truth, 2)
    assert np.all(np.diff(rise) >= -1e-9) and rise[-1] - rise[0] > 2.0
    assert row.label == "tone_error"
    assert row.produced_tones == ["4", "1", "2"]  # a T3 without its dip is heard as a T2


def test_turn_shift_moves_the_turning_point_by_the_given_time(src):
    turn = {}
    for ms in (-80.0, 80.0):
        _, truth, row = synth.perturb(src, "turn_shift", {"index": 2, "ms": ms}, 0)
        turn[ms] = int(np.nanargmin(semitones(truth)[slice(*src.voice.extents[2])]))
        assert row.label == "graded"
    assert (turn[80.0] - turn[-80.0]) * 10 == pytest.approx(160, abs=20)  # frames of 10 ms


def test_onset_and_offset_shift_move_only_their_end_of_the_contour(src):
    _, base, _ = synth.perturb(src, "onset_shift", {"index": 0, "chao": 0.5}, 0)
    _, up, _ = synth.perturb(src, "onset_shift", {"index": 0, "chao": 1.5}, 0)
    _, down, _ = synth.perturb(src, "offset_shift", {"index": 0, "chao": -1.5}, 0)
    _, plain, _ = synth.perturb(src, "offset_shift", {"index": 0, "chao": 0.5}, 0)
    register = src.voice.ceil - src.voice.floor
    assert core(src, up, 0)[0] - core(src, base, 0)[0] == pytest.approx(register / 4, abs=0.05)
    assert core(src, up, 0)[-1] == pytest.approx(core(src, base, 0)[-1], abs=0.05)
    assert core(src, plain, 0)[-1] - core(src, down, 0)[-1] == pytest.approx(
        2 * register / 4, abs=0.05
    )
    assert core(src, plain, 0)[0] == pytest.approx(core(src, down, 0)[0], abs=0.05)


def test_neutral_full_gives_a_neutral_syllable_a_full_tone(src_neutral):
    _, truth, row = synth.perturb(src_neutral, "neutral_full", {"index": 1, "to": "1"}, 0)
    level = core(src_neutral, truth, 1)
    assert np.ptp(level) < 0.1  # T1 is level, at the top of the register
    assert level[0] == pytest.approx(src_neutral.voice.ceil, abs=0.05)
    assert row.label == "tone_error" and row.produced_tones == ["1", "1", "2"]


def test_the_join_is_blended_over_two_frames_each_side_of_the_syllable(src):
    """The source's syllable 2 has voiced frames (WORLD's, not tonekit's) just before its core;
    they move 2/3 and then 1/3 of the way toward the new contour's onset; the frame after is
    untouched."""
    start, _ = src.voice.extents[2]
    assert src.world.f0[start - 3 : start].all()  # the voiced neighbours this test relies on
    _, truth, _ = synth.perturb(src, "tone_swap", {"index": 2, "to": "2"}, 0)
    _, identity, _ = synth.perturb(src, "identity", {}, 0)
    new, old = semitones(truth), semitones(identity)
    onset = new[start]
    assert new[start - 1] == pytest.approx(2 / 3 * onset + 1 / 3 * old[start - 1])
    assert new[start - 2] == pytest.approx(1 / 3 * onset + 2 / 3 * old[start - 2])
    assert new[start - 3] == pytest.approx(old[start - 3])
    assert abs(new[start - 1] - onset) < abs(old[start - 1] - onset)  # a smaller jump than before


def test_a_neutral_syllable_is_perturbed_from_the_context_fallback_contour(src_neutral):
    """The neutral tone has no citation contour in the pack; the harness draws it as 3 -> 2."""
    register = src_neutral.voice.ceil - src_neutral.voice.floor
    _, truth, row = synth.perturb(src_neutral, "onset_shift", {"index": 1, "chao": 1.0}, 0)
    contour = core(src_neutral, truth, 1)
    assert contour[0] == pytest.approx(src_neutral.voice.floor + 3.0 / 4 * register, abs=0.05)
    assert contour[-1] == pytest.approx(src_neutral.voice.floor + 1.0 / 4 * register, abs=0.05)
    assert row.label == "graded" and row.produced_tones == ["1", "5", "2"]
    with pytest.raises(SynthError, match="turn_shift: index 1 is not a syllable"):
        synth.perturb(src_neutral, "turn_shift", {"index": 1, "ms": 60.0}, 0)


def test_the_new_contour_is_drawn_in_the_sources_own_register(src):
    """T4's onset is Chao 5, the source register's ceiling; its end is Chao 1, the floor."""
    _, truth, _ = synth.perturb(src, "tone_swap", {"index": 1, "to": "4"}, 0)
    fall = core(src, truth, 1)
    assert fall[0] == pytest.approx(src.voice.ceil, abs=0.05)
    assert fall[-1] == pytest.approx(src.voice.floor, abs=0.05)


# ---- bounds and validation -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("family", "params", "message"),
    [
        ("range_compress", {"factor": 0.3}, r"range_compress: factor 0\.3 is outside \[0\.4, 0\.8"),
        ("range_compress", {"factor": 0.9}, r"range_compress: factor 0\.9 is outside"),
        ("turn_shift", {"index": 2, "ms": 30.0}, r"turn_shift: ms 30 is outside a magnitude in"),
        ("turn_shift", {"index": 2, "ms": -130.0}, r"turn_shift: ms -130 is outside"),
        ("onset_shift", {"index": 0, "chao": 0.2}, r"onset_shift: chao 0\.2 is outside"),
        ("offset_shift", {"index": 0, "chao": 1.6}, r"offset_shift: chao 1\.6 is outside"),
        ("noise", {"snr_db": 4.0}, r"noise: snr_db 4 is outside \[5, 20\]"),
        ("noise", {"snr_db": 21.0}, r"noise: snr_db 21 is outside"),
        ("register_shift", {"st": 6.5}, r"register_shift: st 6\.5 is outside \[-6, 6\]"),
        ("rate", {"factor": 1.3}, r"rate: factor 1\.3 is outside \[0\.8, 1\.25\]"),
        ("rate", {"factor": float("nan")}, r"rate: factor nan is not a finite number"),
        ("rate", {"factor": "fast"}, r"rate: factor 'fast' is not a finite number"),
        ("tone_swap", {"index": 1, "to": "1"}, r"tone_swap: to '1' must be one of \['2', '3'"),
        ("tone_swap", {"index": 1, "to": "5"}, r"tone_swap: to '5' must be one of"),
        ("tone_swap", {"index": 7, "to": "2"}, r"tone_swap: index 7 is not a syllable"),
        ("tone_swap", {"index": True, "to": "2"}, r"tone_swap: index True is not a syllable"),
        ("t3_no_dip", {"index": 0}, r"t3_no_dip: index 0 is not a syllable this family can target"),
        ("neutral_full", {"index": 1, "to": "2"}, r"neutral_full: index 1 is not a syllable"),
        ("turn_shift", {"index": 0, "ms": 60.0}, r"turn_shift: index 0 is not a syllable"),
        ("tone_swap", {"index": 1}, r"tone_swap: missing parameter 'to'"),
        ("noise", {}, r"noise: missing parameter 'snr_db'"),
        ("noise", {"snr_db": 10.0, "colour": "pink"}, r"noise: unknown parameter 'colour'"),
        ("noise", {"snr_db": 10.0, "noise_wav": 3}, r"noise: noise_wav 3 is not a path"),
        ("teleport", {}, r"unknown family 'teleport'; known: identity, tone_swap"),
    ],
)
def test_out_of_bounds_or_invalid_parameters_are_a_synth_error(src, family, params, message):
    with pytest.raises(SynthError, match=message):
        synth.perturb(src, family, params, 0)


@pytest.mark.parametrize(
    ("family", "params"),
    [
        ("range_compress", {"factor": 0.4}),
        ("range_compress", {"factor": 0.8}),
        ("turn_shift", {"index": 2, "ms": -40.0}),
        ("turn_shift", {"index": 2, "ms": 120.0}),
        ("turn_shift", {"index": 2, "ms": -120.0}),
        ("turn_shift", {"index": 2, "ms": 40.0}),
        ("onset_shift", {"index": 0, "chao": -0.5}),
        ("onset_shift", {"index": 0, "chao": 1.5}),
        ("offset_shift", {"index": 0, "chao": -1.5}),
        ("offset_shift", {"index": 0, "chao": 0.5}),
        ("noise", {"snr_db": 5.0}),
        ("noise", {"snr_db": 20.0}),
        ("register_shift", {"st": 6.0}),
        ("register_shift", {"st": -6.0}),
        ("rate", {"factor": 0.8}),
        ("rate", {"factor": 1.25}),
    ],
)
def test_every_bound_is_inclusive(src, family, params):
    """The value at either end is accepted as given: recorded in the row as it was, not clamped,
    rounded or moved."""
    audio, truth, row = synth.perturb(src, family, params, 0)
    recorded = row.synthetic["params"]
    assert row.synthetic["family"] == family
    assert {name: recorded[name] for name in params} == params
    assert len(audio) > 0 and len(truth) == len(audio) // HOP + 1


def test_a_numpy_integer_index_is_accepted_and_recorded_as_a_plain_int(src):
    params = {"index": np.int64(1), "to": "4"}
    audio, _, row = synth.perturb(src, "tone_swap", params, 0)
    assert row.synthetic["params"] == {"index": 1, "to": "4"}
    assert type(row.synthetic["params"]["index"]) is int
    json.dumps(row.synthetic)  # a numpy integer would not serialise
    again = synth.perturb(src, "tone_swap", {"index": 1, "to": "4"}, 0)
    assert row == again[2]
    np.testing.assert_array_equal(audio, again[0])
    with pytest.raises(SynthError, match="index np.int64\\(7\\) is not a syllable"):
        synth.perturb(src, "tone_swap", {"index": np.int64(7), "to": "2"}, 0)
    _, _, numpy_float = synth.perturb(src, "range_compress", {"factor": np.float32(0.5)}, 0)
    assert numpy_float.synthetic["params"] == {"factor": 0.5}


def test_the_neutral_tone_is_never_a_tone_swap_source_or_target(src_neutral):
    with pytest.raises(SynthError, match="tone_swap: index 1 is not a syllable"):
        synth.perturb(src_neutral, "tone_swap", {"index": 1, "to": "2"}, 0)
    with pytest.raises(SynthError, match="tone_swap: to '5' must be one of"):
        synth.perturb(src_neutral, "tone_swap", {"index": 0, "to": "5"}, 0)
    with pytest.raises(SynthError, match="neutral_full: to '5' must be one of"):
        synth.perturb(src_neutral, "neutral_full", {"index": 1, "to": "5"}, 0)
