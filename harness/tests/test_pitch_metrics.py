"""GPE and VDE on hand-made tracks: exact values, the None case and the length check."""

from __future__ import annotations

import pytest

from tonekit_harness.pitch_metrics import Counts, count, gpe, vde


def test_gpe_counts_frames_voiced_in_both_whose_error_exceeds_20_percent():
    est = [100.0, 130.0, 100.0, None, 100.0]
    truth = [100.0, 100.0, None, 100.0, 79.0]
    # voiced in both: frames 0 (0%), 1 (30%) and 4 (100 vs 79: 26.6%); frames 2 and 3 do not count
    assert gpe(est, truth) == pytest.approx(2 / 3)


def test_gpe_is_relative_to_the_truth_and_exactly_20_percent_is_not_an_error():
    assert gpe([120.0], [100.0]) == 0.0  # |120 - 100| / 100 = 0.2 exactly
    assert gpe([80.0], [100.0]) == 0.0  # 0.2 again, below
    assert gpe([100.0], [80.0]) == 1.0  # 20 / 80 = 0.25: the denominator is the truth, not the estimate
    assert gpe([79.0], [100.0]) == 1.0  # 0.21


def test_gpe_of_a_perfect_track_is_zero_and_of_an_octave_error_track_is_one():
    truth = [100.0, 110.0, 120.0]
    assert gpe(truth, truth) == 0.0
    assert gpe([200.0, 220.0, 240.0], truth) == 1.0
    assert gpe([50.0, 55.0, 60.0], truth) == 1.0  # half is 50% off


def test_gpe_is_none_when_no_frame_is_voiced_in_both():
    assert gpe([None, 100.0], [100.0, None]) is None
    assert gpe([None, None], [None, None]) is None
    assert gpe([], []) is None


def test_vde_counts_frames_whose_voicing_differs_over_all_frames():
    est = [100.0, None, 100.0, None]
    truth = [100.0, 100.0, None, None]
    assert vde(est, truth) == 0.5  # frames 1 and 2 differ; both unvoiced and both voiced agree


def test_vde_ignores_the_pitch_value_and_is_zero_for_identical_voicing():
    assert vde([100.0, None, 300.0], [200.0, None, 100.0]) == 0.0
    assert vde([None, None], [100.0, 100.0]) == 1.0


def test_vde_of_no_frames_is_none():
    assert vde([], []) is None


@pytest.mark.parametrize("metric", [gpe, vde])
def test_unequal_lengths_are_a_value_error_naming_both(metric):
    with pytest.raises(ValueError, match=r"2 frames.*3 frames"):
        metric([100.0, 100.0], [100.0, 100.0, 100.0])


def test_counts_pool_over_clips_so_the_rates_are_frame_weighted():
    a = count([100.0, 130.0], [100.0, 100.0])  # 2 frames, both voiced in 2, one gross error
    b = count([None, 100.0, 100.0], [100.0, 100.0, None])  # 3 frames, both voiced in 1, voicing differs in 2
    assert (a.frames, a.both_voiced, a.gross_errors, a.voicing_errors) == (2, 2, 1, 0)
    assert (b.frames, b.both_voiced, b.gross_errors, b.voicing_errors) == (3, 1, 0, 2)
    pooled = a + b
    assert (pooled.frames, pooled.both_voiced, pooled.gross_errors, pooled.voicing_errors) == (5, 3, 1, 2)
    assert pooled.gpe == pytest.approx(1 / 3)  # not the mean of 1/2 and 0
    assert pooled.vde == pytest.approx(2 / 5)


def test_no_counts_have_no_rates():
    assert Counts().gpe is None and Counts().vde is None
