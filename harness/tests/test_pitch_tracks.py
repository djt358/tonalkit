"""The f0 tracks on tonekit's 10 ms grid: SwiftF0's 16 ms frames resampled onto it (without the
model, on hand-built frames), tonekit's own track read back from an Analysis, and SwiftF0 itself
on a harmonic tone."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
import tonekit_py
from support import RATE, utterance

from tonekit_harness import pitch_tracks
from tonekit_harness.pitch_tracks import pyin_track, resample, swiftf0_track, track_hz

HOP = 160
SWIFT_HOP = 256


def swift_times(n: int) -> np.ndarray:
    """SwiftF0's frame times: frame k is centred at k * 16 ms."""
    return np.arange(n) * SWIFT_HOP / RATE


def st(hz: float) -> float:
    return 12 * math.log2(hz / 55.0)


def hz_of(semitones: float) -> float:
    return 55.0 * 2 ** (semitones / 12)


# ---- resample: SwiftF0's frames onto the 10 ms grid --------------------------------------------


def test_hz_is_interpolated_in_semitones_and_voiced_p_linearly():
    # frames at 0, 16, 32 ms; grid frame 1 is at 10 ms (5/8 of the way from frame 0 to frame 1)
    # and grid frame 2 at 20 ms (1/4 of the way from frame 1 to frame 2)
    frames = resample(swift_times(3), [100.0, 200.0, 100.0], [1.0, 0.95, 1.0], n_frames=4)
    assert frames[0] == {"hz": pytest.approx(100.0), "voiced_p": pytest.approx(1.0)}
    assert frames[1]["hz"] == pytest.approx(hz_of(st(100.0) + 0.625 * 12))
    assert frames[1]["voiced_p"] == pytest.approx(1.0 - 0.05 * 0.625)
    assert frames[2]["hz"] == pytest.approx(hz_of(st(200.0) - 0.25 * 12))
    assert frames[2]["voiced_p"] == pytest.approx(0.95 + 0.05 * 0.25)


def test_a_grid_frame_is_voiced_only_when_the_interpolated_confidence_reaches_0_9():
    # 20 ms lies 1/4 of the way from frame 1 (confidence 1.0) to frame 2: 0.75 + 0.25 * b
    voiced = resample(swift_times(3), [100.0] * 3, [1.0, 1.0, 0.7], n_frames=3)[2]
    unvoiced = resample(swift_times(3), [100.0] * 3, [1.0, 1.0, 0.5], n_frames=3)[2]
    assert voiced["hz"] == pytest.approx(100.0) and voiced["voiced_p"] == pytest.approx(0.925)
    assert unvoiced["hz"] is None and unvoiced["voiced_p"] == pytest.approx(0.875)


def test_an_unvoiced_frames_pitch_never_reaches_the_grid():
    # the middle frame is unvoiced by SwiftF0's own rule (confidence < 0.5) and its pitch is junk
    frames = resample(swift_times(3), [100.0, 400.0, 100.0], [1.0, 0.1, 1.0], n_frames=4)
    assert [f["hz"] is not None for f in frames] == [True, False, False, False]
    assert frames[0]["hz"] == pytest.approx(100.0)


def test_a_voiced_neighbour_supplies_the_pitch_when_the_other_bracketing_frame_is_unvoiced():
    # 50 ms is 1/8 of the way from frame 3 (48 ms, confidence 1.0) to frame 4 (64 ms, confidence
    # 0.4, unvoiced by SwiftF0's own rule): 0.875 + 0.125 * 0.4 = 0.925 is voiced, at frame 3's
    # pitch
    hz = [100.0, 100.0, 100.0, 130.0, 300.0]
    frame = resample(swift_times(5), hz, [1.0, 1.0, 1.0, 1.0, 0.4], n_frames=6)[5]
    assert frame["hz"] == pytest.approx(130.0)
    assert frame["voiced_p"] == pytest.approx(0.925)


def test_a_grid_frame_beyond_the_last_swiftf0_frame_is_unvoiced_with_voiced_p_zero():
    # the last SwiftF0 frame is at 48 ms: grid frames at 0..40 ms are covered, 50 ms is not
    frames = resample(swift_times(4), [100.0] * 4, [1.0] * 4, n_frames=7)
    assert [f["hz"] is not None for f in frames] == [True] * 5 + [False] * 2
    assert frames[5] == {"hz": None, "voiced_p": 0.0} == frames[6]


def test_the_last_swiftf0_frame_time_is_covered_when_it_is_on_the_grid():
    # frame 5 is at 80 ms, exactly grid frame 8
    frames = resample(swift_times(6), [100.0] * 6, [1.0] * 6, n_frames=10)
    assert frames[8]["hz"] == pytest.approx(100.0) and frames[8]["voiced_p"] == pytest.approx(1.0)
    assert frames[9] == {"hz": None, "voiced_p": 0.0}


def test_a_single_swiftf0_frame_covers_only_the_first_grid_frame():
    frames = resample(swift_times(1), [120.0], [0.99], n_frames=3)
    assert frames[0] == {"hz": pytest.approx(120.0), "voiced_p": pytest.approx(0.99)}
    assert frames[1:] == [{"hz": None, "voiced_p": 0.0}] * 2


def test_a_frame_without_a_usable_pitch_is_not_voiced_whatever_its_confidence():
    # frame 2 (32 ms) has confidence 1.0 but no pitch: 20 ms is nearest to frame 1 and takes its
    # pitch, 30 ms is nearest to frame 2 and is unvoiced
    frames = resample(swift_times(4), [100.0, 100.0, 0.0, 100.0], [1.0] * 4, n_frames=4)
    assert frames[2]["hz"] == pytest.approx(100.0)
    assert frames[3]["hz"] is None


def test_the_frame_count_is_whatever_the_grid_asks_for():
    assert len(resample(swift_times(10), [100.0] * 10, [1.0] * 10, n_frames=1)) == 1
    assert len(resample(swift_times(10), [100.0] * 10, [1.0] * 10, n_frames=40)) == 40


# ---- reading tracks back -----------------------------------------------------------------------


def test_track_hz_reads_an_f0_track_and_drops_what_tonekit_would_drop():
    f0 = {
        "frames": [
            {"hz": 100.0, "voiced_p": 1.0},
            {"hz": None, "voiced_p": 0.0},
            {"hz": 0.0, "voiced_p": 0.9},
            {"hz": -5.0, "voiced_p": 0.9},
            {"hz": float("nan"), "voiced_p": 0.9},
            {"hz": 250.5, "voiced_p": 0.1},
        ],
        "provider": "test",
    }
    assert track_hz(json.dumps(f0)) == [100.0, None, None, None, None, 250.5]


def test_pyin_track_counts_a_frame_voiced_when_it_has_a_pitch_whatever_its_voiced_p():
    """R32: a voiced frame is `hz.is_some()`; `voiced_p` is only a confidence weight."""
    analysis = {
        "f0": {
            "frames": [
                {"hz": 100.0, "voiced_p": 0.9},
                {"hz": 120.0, "voiced_p": 0.3},
                {"hz": None, "voiced_p": 0.8},
            ],
            "provider": "pyin",
        }
    }
    assert pyin_track(json.dumps(analysis)) == [100.0, 120.0, None]


def test_pyin_track_of_a_real_analysis_has_a_frame_per_10_ms_and_pitch_in_the_voice_range():
    pcm = utterance(["4", "1", "3"])
    hz = pyin_track(tonekit_py.analyze(pcm, RATE))
    assert len(hz) == len(pcm) // HOP + 1
    voiced = [h for h in hz if h is not None]
    # three 250 ms syllables is 75 frames; the voice is 100-200 Hz
    assert len(voiced) > 60 and all(90.0 < h < 220.0 for h in voiced)


# ---- SwiftF0 on audio --------------------------------------------------------------------------


def harmonic_tone(hz: float, seconds: float) -> np.ndarray:
    t = np.arange(round(seconds * RATE))
    phase = 2 * np.pi * hz * t / RATE
    wave = sum(np.sin(k * phase) / k for k in range(1, 9))
    return (0.5 * wave / np.abs(wave).max()).astype(np.float32)


def test_swiftf0_track_of_a_150_hz_tone_is_within_2_percent_on_at_least_90_percent_of_frames():
    pcm = harmonic_tone(150.0, 1.5)
    track = json.loads(swiftf0_track(pcm))
    assert len(track["frames"]) == len(pcm) // HOP + 1
    hz = track_hz(json.dumps(track))
    close = [h is not None and abs(h - 150.0) / 150.0 < 0.02 for h in hz]
    assert sum(close) / len(close) >= 0.9


def test_swiftf0_track_names_its_provider_with_the_package_version():
    track = json.loads(swiftf0_track(harmonic_tone(150.0, 0.5)))
    assert track["provider"] == pitch_tracks.provider_identity("swift-f0")
    assert track["provider"].startswith("swift-f0 ") and track["provider"] != "swift-f0 "
    assert all(0.0 <= f["voiced_p"] <= 1.0 for f in track["frames"])


def test_swiftf0_track_length_follows_the_grid_for_lengths_off_a_frame_boundary():
    for extra in (0, 1, 79, 159):
        pcm = harmonic_tone(150.0, 0.6)[: 8000 + extra]
        assert len(json.loads(swiftf0_track(pcm))["frames"]) == (8000 + extra) // HOP + 1


def test_swiftf0_track_is_deterministic():
    pcm = harmonic_tone(150.0, 0.5)
    assert swiftf0_track(pcm) == swiftf0_track(pcm)


def test_swiftf0_track_of_digital_silence_is_all_unvoiced():
    hz = track_hz(swiftf0_track(np.zeros(8000, dtype=np.float32)))
    assert hz == [None] * (8000 // HOP + 1)


def test_tonekit_takes_the_swiftf0_track_as_its_f0():
    pcm = utterance(["4", "1", "3"])
    f0_json = swiftf0_track(pcm)
    analysis = json.loads(tonekit_py.analyze(pcm, RATE, None, f0_json))
    assert analysis["f0"]["provider"] == "external"
    assert len(analysis["f0"]["frames"]) == len(pcm) // HOP + 1
    assert len(analysis["nuclei"]) == 3  # one per syllable: the track is good enough to segment


# ---- named providers ---------------------------------------------------------------------------


def test_a_named_provider_gives_the_same_track_as_calling_it_directly():
    pcm = harmonic_tone(150.0, 0.5)
    assert pitch_tracks.provider_track("swift-f0", pcm) == swiftf0_track(pcm)


def test_an_unknown_provider_is_a_value_error_naming_the_known_ones():
    with pytest.raises(ValueError, match=r"unknown f0 provider 'crepe'.*swift-f0"):
        pitch_tracks.provider_track("crepe", np.zeros(1600, dtype=np.float32))
    with pytest.raises(ValueError, match="unknown f0 provider 'crepe'"):
        pitch_tracks.provider_identity("crepe")


# ---- SwiftF0's input gain ----------------------------------------------------------------------


def voiced_frames(pcm: np.ndarray) -> np.ndarray:
    return np.array([h is not None for h in track_hz(swiftf0_track(pcm))])


def dilate(mask: np.ndarray, frames: int = 1) -> np.ndarray:
    padded = np.pad(mask, frames)
    return np.array([padded[i : i + 2 * frames + 1].any() for i in range(len(mask))])


def test_a_very_quiet_clip_is_voiced_where_the_same_clip_at_normal_level_is():
    """SwiftF0 does not normalise its input (its README: scale a recording peaking below about
    -35 dBFS first); the harness applies that rule so a quiet clip is not handicapped."""
    normal = utterance(["4", "1", "3"])
    quiet = (normal * 10 ** (-44 / 20)).astype(np.float32)  # peaks near -50 dBFS
    assert 20 * np.log10(np.abs(quiet).max()) == pytest.approx(-50.0, abs=0.5)
    loud, soft = voiced_frames(normal), voiced_frames(quiet)
    assert loud.sum() > 60  # the reference really is voiced
    assert not (loud & ~dilate(soft)).any()  # nothing voiced at normal level is lost when quiet
    assert not (soft & ~dilate(loud)).any()  # and nothing appears


def test_a_clip_above_the_threshold_is_fed_unchanged():
    normal = utterance(["4", "1", "3"])
    assert 20 * np.log10(np.abs(normal).max()) > pitch_tracks.QUIET_PEAK_DBFS
    assert np.array_equal(pitch_tracks.swiftf0_input(normal), normal)
    threshold = 10 ** (pitch_tracks.QUIET_PEAK_DBFS / 20)
    at = np.array([0.0, threshold, -0.5 * threshold], dtype=np.float32)
    assert np.array_equal(
        pitch_tracks.swiftf0_input(at), at
    )  # a peak at the threshold is not quiet


def test_the_gain_rule_scales_only_quiet_clips_to_a_peak_of_half():
    quiet = np.array([0.0, 0.004, -0.008, 0.002], dtype=np.float32)  # peak -42 dBFS
    fed = pitch_tracks.swiftf0_input(quiet)
    assert np.abs(fed).max() == pytest.approx(0.5)
    np.testing.assert_allclose(fed, quiet / 0.008 * 0.5)
    silence = np.zeros(100, dtype=np.float32)
    assert np.array_equal(pitch_tracks.swiftf0_input(silence), silence)  # no peak, no gain
    loud = np.array([0.0, 0.3, -0.2], dtype=np.float32)
    assert np.array_equal(pitch_tracks.swiftf0_input(loud), loud)
