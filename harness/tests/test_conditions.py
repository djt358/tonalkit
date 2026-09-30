"""Which condition a synthetic clip belongs to: clean, or a noise clip in its nearest SNR bucket."""

from __future__ import annotations

import pytest
from support import candidate

from tonekit_harness import conditions
from tonekit_harness.manifest import Clip, Condition


def row(family: str | None, params: dict | None = None, noise: str = "none") -> Clip:
    """A manifest row with only what `conditions.condition` looks at."""
    synthetic = None if family is None else {"family": family, "params": params or {}}
    return Clip(
        id="c", path="c.wav", speaker="s", set="synthetic", label="correct",
        intended=candidate(["1"]), condition=Condition(noise=noise, distance="synthetic"),
        source="synthetic-world", synthetic=synthetic,
    )  # fmt: skip


@pytest.mark.parametrize(
    ("clip", "want"),
    [
        (row("identity"), "clean"),
        (row("tone_swap", {"index": 1, "to": "4"}), "clean"),
        (row("rate", {"factor": 1.1}), "clean"),
        (row(None), "clean"),
        (row("noise", {"snr_db": 5.0}), "noise ~5 dB"),
        (row("noise", {"snr_db": 7.5}), "noise ~5 dB"),  # halfway between two buckets: the lower
        (row("noise", {"snr_db": 7.6}), "noise ~10 dB"),
        (row("noise", {"snr_db": 10.0}), "noise ~10 dB"),
        (row("noise", {"snr_db": 15.0}), "noise ~10 dB"),
        (row("noise", {"snr_db": 15.1}), "noise ~20 dB"),
        (row("noise", {"snr_db": 20}), "noise ~20 dB"),
        (row("noise", {"snr_db": 2.0}), "noise ~5 dB"),  # beyond the buckets: the nearest
        (
            row("noise", {}, noise="cafe 12 dB"),
            "cafe 12 dB",
        ),  # no SNR to bucket: the row's own words
    ],
)
def test_a_clip_is_clean_or_a_noise_clip_in_its_nearest_snr_bucket(clip, want):
    assert conditions.condition(clip) == want


def test_the_buckets_read_as_a_phrase_from_the_constant(monkeypatch):
    assert conditions.buckets_text() == "5, 10 and 20 dB"
    monkeypatch.setattr(conditions, "NOISE_BUCKETS_DB", (3.0, 6.0))
    assert conditions.buckets_text() == "3 and 6 dB"
    monkeypatch.setattr(conditions, "NOISE_BUCKETS_DB", (12.0,))
    assert conditions.buckets_text() == "12 dB"


def test_conditions_are_ordered_clean_then_noise_by_snr_then_the_rest_by_name():
    names = ["zzz", "noise ~20 dB", "clean", "aaa", "noise ~5 dB", "noise ~10 dB"]
    assert sorted(names, key=conditions.order) == [
        "clean", "noise ~5 dB", "noise ~10 dB", "noise ~20 dB", "aaa", "zzz",
    ]  # fmt: skip
