"""The synthetic test voice in `support.py`, which Task 16 reuses: the neutral tone, the duration
keywords and writing given audio as a manifest clip."""

from __future__ import annotations

import numpy as np
from scipy.io import wavfile
from support import GAP_S, RATE, SYLLABLE_S, make_clip, syllable, utterance, write_clip


def test_the_neutral_tone_is_half_a_syllable_long():
    assert len(syllable("4")) == 4_000  # 250 ms
    assert len(syllable("5")) == 2_000
    assert len(syllable("5", 0.5)) == 4_000  # half of the requested duration


def test_syllable_and_gap_durations_are_keywords_defaulting_to_the_constants():
    # Two 300 ms edges (9 600 samples), the syllables and the gaps between them.
    assert len(utterance(["1", "2"])) == 9_600 + 2 * 4_000 + 2_400
    assert len(utterance(["1", "2", "3"])) == 9_600 + 3 * 4_000 + 2 * 2_400
    assert len(utterance(["1", "5"])) == 9_600 + 4_000 + 2_000 + 2_400
    assert len(utterance(["1", "2"], syllable_s=0.3, gap_s=0.2)) == 9_600 + 2 * 4_800 + 3_200
    explicit = utterance(["1", "2"], syllable_s=SYLLABLE_S, gap_s=GAP_S)
    assert np.array_equal(explicit, utterance(["1", "2"]))


def test_write_clip_writes_the_given_audio_and_describes_it(tmp_path):
    pcm = np.linspace(-0.5, 0.5, 1_600)  # float64: written as float32
    clip = write_clip(
        tmp_path / "audio", "c1", pcm, intended=["1", "2"], set="synthetic", label="graded",
        pair="p", speaker="ann", distractors=[["1", "3"]],
    )  # fmt: skip
    rate, samples = wavfile.read(tmp_path / "audio" / "c1.wav")
    assert rate == RATE and samples.dtype == np.float32
    assert np.array_equal(samples, pcm.astype(np.float32))
    assert (clip.id, clip.path, clip.speaker, clip.set, clip.pair, clip.label) == (
        "c1", "c1.wav", "ann", "synthetic", "p", "graded"
    )  # fmt: skip
    assert clip.intended.tones == ["1", "2"]
    assert [d.tones for d in clip.distractors] == [["1", "3"]]
    assert clip.produced_tones is None  # not a plain rendering of tones


def test_make_clip_synthesises_and_writes_through_write_clip(tmp_path):
    clip = make_clip(
        tmp_path, "m1", ["4", "5"], intended=["4", "1"], seed=3, syllable_s=0.2, gap_s=0.1
    )
    _, samples = wavfile.read(tmp_path / clip.path)
    assert np.array_equal(samples, utterance(["4", "5"], 3, syllable_s=0.2, gap_s=0.1))
    assert clip.produced_tones == ["4", "5"] and clip.intended.tones == ["4", "1"]
