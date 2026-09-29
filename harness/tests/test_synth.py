"""WORLD resynthesis and the perturbation families, on the numpy harmonic test voice (never DJ's
audio). Each family is checked through the ground-truth f0 it reports, which is exactly the f0
handed to WORLD; the direction check at the end asks tonekit itself."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest
from support import RATE, make_clip, utterance, write_clip

from tonekit_harness import cli, evaluate, manifest, synth, world
from tonekit_harness.families import FAMILIES
from tonekit_harness.synth import SynthError

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"
HOP = 160


@pytest.fixture(scope="module")
def pack_toml() -> str:
    return (PACKS / "cmn.toml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def calib_json() -> str:
    return (PACKS / "cmn.calib.json").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("synth-sources")


def quiet_clip(root: Path, cid: str, tones: list[str], **kw):
    """A support-voice clip at half amplitude, so resynthesis plus noise cannot clip."""
    return write_clip(root, cid, 0.5 * utterance(tones), intended=tones, produced=tones, **kw)


@pytest.fixture(scope="module")
def src(root, pack_toml, calib_json) -> synth.Source:
    """T4 T1 T3: syllable 1 is level, syllable 2 dips."""
    clip = quiet_clip(root, "src-413", ["4", "1", "3"])
    return synth.prepare(clip, root=root, pack_toml=pack_toml, calib_json=calib_json)


@pytest.fixture(scope="module")
def src_neutral(root, pack_toml, calib_json) -> synth.Source:
    """T1 T5 T2: syllable 1 is the neutral tone."""
    clip = quiet_clip(root, "src-152", ["1", "5", "2"])
    return synth.prepare(clip, root=root, pack_toml=pack_toml, calib_json=calib_json)


def semitones(hz: list[float | None]) -> np.ndarray:
    return np.array([np.nan if h is None else 12 * np.log2(h / 55.0) for h in hz])


def core(src: synth.Source, truth: list[float | None], index: int) -> np.ndarray:
    """The truth's semitones over syllable `index`'s voiced core, unvoiced frames dropped."""
    start, end = src.voice.extents[index]
    st = semitones(truth)[start:end]
    return st[~np.isnan(st)]


# ---- WORLD ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("extra", [0, 1, 79, 159])
def test_world_analysis_is_on_tonekits_grid(extra):
    pcm = np.concatenate([utterance(["1", "2"]), np.zeros(extra, dtype=np.float32)])
    w = world.analyse(pcm)
    assert len(w.f0) == len(w.sp) == len(w.ap) == len(pcm) // 160 + 1
    assert len(world.synthesise(w, len(pcm))) == len(pcm)
    assert world.synthesise(w).dtype == np.float32


def test_world_resynthesis_keeps_the_pitch(src):
    """Resynthesis of the analysed f0 is voiced where the source is, and at the pitch given."""
    truth = synth.perturb(src, "identity", {}, 0)[1]
    assert [h is not None for h in truth] == list(src.world.f0 > 0)
    y = world.synthesise(world.analyse(src.pcm), len(src.pcm))
    assert len(y) == len(src.pcm) and np.abs(y).max() > 0.1


# ---- the brief's checks ---------------------------------------------------------------------------


def test_tone_swap_of_a_level_syllable_to_4_falls_over_the_syllable(src):
    _, truth, row = synth.perturb(src, "tone_swap", {"index": 1, "to": "4"}, 1)
    _, identity, _ = synth.perturb(src, "identity", {}, 1)

    fall = core(src, truth, 1)
    assert row.label == "tone_error"
    assert fall[0] - fall[-1] > 6.0  # a T4 falls most of the register
    assert np.all(np.diff(fall) <= 1e-9)  # and falls all the way
    level = core(src, identity, 1)
    assert abs(level[0] - level[-1]) < 1.5  # the source syllable it replaced was level


def test_noise_leaves_f0_unchanged_and_is_correct(src):
    audio, truth, row = synth.perturb(src, "noise", {"snr_db": 10.0}, 3)
    clean, clean_truth, _ = synth.perturb(src, "identity", {}, 3)

    assert truth == clean_truth
    assert row.label == "correct"
    voiced = np.zeros(len(clean), dtype=bool)
    for i, h in enumerate(clean_truth):
        if h is not None:
            voiced[max(0, i * HOP - HOP // 2) : i * HOP + HOP // 2] = True
    added = audio.astype(np.float64) - clean
    snr = 10 * np.log10(np.mean(clean[voiced] ** 2.0) / np.mean(added**2.0))
    assert snr == pytest.approx(10.0, abs=0.1)  # relative to the voiced speech power


@pytest.mark.parametrize(
    ("family", "params"),
    [
        ("identity", {}),
        ("tone_swap", {"index": 0, "to": "2"}),
        ("t3_no_dip", {"index": 2}),
        ("range_compress", {"factor": 0.5}),
        ("turn_shift", {"index": 2, "ms": 80.0}),
        ("onset_shift", {"index": 0, "chao": -1.0}),
        ("offset_shift", {"index": 1, "chao": 1.5}),
        ("noise", {"snr_db": 5.0}),
        ("register_shift", {"st": -6.0}),
    ],
)
def test_length_is_preserved_by_every_family_but_rate(src, family, params):
    audio, truth, _ = synth.perturb(src, family, params, 0)
    assert len(audio) == len(src.pcm)
    assert audio.dtype == np.float32
    assert len(truth) == len(audio) // HOP + 1


def test_rate_shortens_when_faster_and_truth_stays_on_the_new_grid(src):
    fast_audio, fast_truth, _ = synth.perturb(src, "rate", {"factor": 1.25}, 0)
    slow_audio, slow_truth, _ = synth.perturb(src, "rate", {"factor": 0.8}, 0)
    n = len(src.pcm)
    assert abs(len(fast_audio) - n / 1.25) <= HOP  # factor > 1 is faster, so shorter
    assert abs(len(slow_audio) - n / 0.8) <= HOP
    assert len(fast_truth) == len(fast_audio) // HOP + 1
    assert len(slow_truth) == len(slow_audio) // HOP + 1
    # the pitch itself is not moved: the voiced frames' median semitones match
    ident = np.nanmedian(semitones(synth.perturb(src, "identity", {}, 0)[1]))
    assert np.nanmedian(semitones(fast_truth)) == pytest.approx(ident, abs=0.5)


# ---- the families' effects on the ground truth ---------------------------------------------------


def test_unvoiced_frames_stay_none_in_the_truth(src):
    _, truth, _ = synth.perturb(src, "tone_swap", {"index": 1, "to": "2"}, 0)
    assert [h is None for h in truth] == list(src.world.f0 == 0)


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


def test_the_new_contour_is_drawn_in_the_sources_own_register(src):
    """T4's onset is Chao 5, the source register's ceiling; its end is Chao 1, the floor."""
    _, truth, _ = synth.perturb(src, "tone_swap", {"index": 1, "to": "4"}, 0)
    fall = core(src, truth, 1)
    assert fall[0] == pytest.approx(src.voice.ceil, abs=0.05)
    assert fall[-1] == pytest.approx(src.voice.floor, abs=0.05)


def test_the_register_is_the_voiced_p5_to_p95(src):
    voiced = 12 * np.log2(src.world.f0[src.world.f0 > 0] / 55.0)
    p5, p95 = np.percentile(voiced, [5, 95])
    assert (src.voice.floor, src.voice.ceil) == pytest.approx((p5, p95))
    assert src.voice.ceil - src.voice.floor > 4.0  # the support voice spans an octave


def test_a_narrow_register_is_widened_symmetrically_to_4_st():
    level = np.full(50, 20.0)
    assert synth.register_bounds(level) == pytest.approx((18.0, 22.0))
    assert synth.register_bounds(np.linspace(19.0, 21.0, 50)) == pytest.approx((18.0, 22.0))
    wide = np.linspace(10.0, 20.0, 101)
    assert synth.register_bounds(wide) == pytest.approx((10.5, 19.5))  # p5 and p95, untouched


# ---- bounds and validation -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("family", "params", "message"),
    [
        ("range_compress", {"factor": 0.3}, r"range_compress: factor 0\.3 is outside \[0\.4, 0\.8\]"),
        ("range_compress", {"factor": 0.9}, r"range_compress: factor 0\.9 is outside"),
        ("turn_shift", {"index": 2, "ms": 30.0}, r"turn_shift: ms 30 is outside a magnitude in \[40, 120\]"),
        ("turn_shift", {"index": 2, "ms": -130.0}, r"turn_shift: ms -130 is outside"),
        ("onset_shift", {"index": 0, "chao": 0.2}, r"onset_shift: chao 0\.2 is outside"),
        ("offset_shift", {"index": 0, "chao": 1.6}, r"offset_shift: chao 1\.6 is outside"),
        ("noise", {"snr_db": 4.0}, r"noise: snr_db 4 is outside \[5, 20\]"),
        ("noise", {"snr_db": 21.0}, r"noise: snr_db 21 is outside"),
        ("register_shift", {"st": 6.5}, r"register_shift: st 6\.5 is outside \[-6, 6\]"),
        ("rate", {"factor": 1.3}, r"rate: factor 1\.3 is outside \[0\.8, 1\.25\]"),
        ("rate", {"factor": float("nan")}, r"rate: factor nan is not a finite number"),
        ("rate", {"factor": "fast"}, r"rate: factor 'fast' is not a finite number"),
        ("tone_swap", {"index": 1, "to": "1"}, r"tone_swap: to '1' must be one of \['2', '3', '4'\]"),
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


def test_every_bound_is_inclusive(src):
    for family, params in [
        ("range_compress", {"factor": 0.4}),
        ("range_compress", {"factor": 0.8}),
        ("turn_shift", {"index": 2, "ms": -40.0}),
        ("turn_shift", {"index": 2, "ms": 120.0}),
        ("noise", {"snr_db": 5.0}),
        ("noise", {"snr_db": 20.0}),
        ("register_shift", {"st": 6.0}),
        ("rate", {"factor": 0.8}),
        ("rate", {"factor": 1.25}),
    ]:
        synth.perturb(src, family, params, 0)


def test_the_neutral_tone_is_never_a_tone_swap_source_or_target(src_neutral):
    with pytest.raises(SynthError, match="tone_swap: index 1 is not a syllable"):
        synth.perturb(src_neutral, "tone_swap", {"index": 1, "to": "2"}, 0)
    with pytest.raises(SynthError, match="tone_swap: to '5' must be one of"):
        synth.perturb(src_neutral, "tone_swap", {"index": 0, "to": "5"}, 0)
    with pytest.raises(SynthError, match="neutral_full: to '5' must be one of"):
        synth.perturb(src_neutral, "neutral_full", {"index": 1, "to": "5"}, 0)


# ---- the manifest rows ----------------------------------------------------------------------------


def test_the_row_says_what_was_done_and_inherits_nothing_that_permits_calibration(src):
    _, _, row = synth.perturb(src, "tone_swap", {"index": 1, "to": "4"}, 7)
    assert re.fullmatch(r"src-413~tone_swap~[0-9a-f]{8}", row.id)
    assert (row.set, row.source, row.label) == ("synthetic", "synthetic-world", "tone_error")
    assert row.synthetic == {
        "from": "src-413",
        "family": "tone_swap",
        "params": {"index": 1, "to": "4"},
        "seed": 7,
    }
    assert row.intended == src.clip.intended
    assert row.produced_tones == ["4", "4", "3"]
    assert row.pair is None and row.needs_listen is False
    assert row.speaker == src.clip.speaker
    assert row.path == f"wav/{row.id}.wav"


def test_non_tone_error_rows_keep_the_sources_produced_tones(src):
    for family, params, label in [
        ("noise", {"snr_db": 10.0}, "correct"),
        ("range_compress", {"factor": 0.6}, "graded"),
        ("rate", {"factor": 1.1}, "correct"),
    ]:
        _, _, row = synth.perturb(src, family, params, 0)
        assert row.produced_tones == ["4", "1", "3"] and row.label == label


def test_the_noise_family_is_recorded_in_the_rows_condition(src):
    _, _, row = synth.perturb(src, "noise", {"snr_db": 10.0}, 0)
    assert row.condition.noise == "pink 10 dB"
    assert row.condition.distance == src.clip.condition.distance
    _, _, plain = synth.perturb(src, "rate", {"factor": 1.1}, 0)
    assert plain.condition == src.clip.condition


def test_the_id_depends_on_the_family_the_parameters_and_the_seed(src):
    ids = {
        synth.perturb(src, "noise", {"snr_db": 10.0}, 0)[2].id,
        synth.perturb(src, "noise", {"snr_db": 10.0}, 1)[2].id,
        synth.perturb(src, "noise", {"snr_db": 12.0}, 0)[2].id,
        synth.perturb(src, "register_shift", {"st": 1.0}, 0)[2].id,
    }
    assert len(ids) == 4
    assert synth.perturb(src, "noise", {"snr_db": 10.0}, 0)[2].id in ids


def test_rows_round_trip_through_write_and_load_and_the_truth_lines_up(src, tmp_path):
    made = [
        synth.perturb(src, "tone_swap", {"index": 1, "to": "4"}, 0),
        synth.perturb(src, "noise", {"snr_db": 10.0}, 0),
        synth.perturb(src, "rate", {"factor": 1.25}, 0),
    ]
    synth.write_corpus(tmp_path, made)

    rows = manifest.load(tmp_path / "manifest.jsonl")
    assert rows == [clip for _, _, clip in made]
    truth = [json.loads(line) for line in (tmp_path / "truth.jsonl").read_text().splitlines()]
    assert [t["id"] for t in truth] == [c.id for c in rows]
    for t, (_, f0, _) in zip(truth, made):
        assert t["f0_hz"] == f0
        assert any(h is None for h in t["f0_hz"]) and any(h is not None for h in t["f0_hz"])
    for (audio, _, clip) in made:
        _, back = evaluate.read_wav(tmp_path / clip.path, clip.id)
        np.testing.assert_array_equal(back, audio)


def test_synthetic_rows_are_gradable_by_evaluate_unchanged(src, tmp_path, pack_toml, calib_json):
    made = [synth.perturb(src, "noise", {"snr_db": 20.0}, 0), synth.perturb(src, "identity", {}, 0)]
    synth.write_corpus(tmp_path, made)
    results = evaluate.run(
        manifest.load(tmp_path / "manifest.jsonl"), pack_toml, calib_json, None,
        root=tmp_path, use_cache=False,
    )  # fmt: skip
    assert [r.set for r in results] == ["synthetic", "synthetic"]
    assert all(r.overall is not None for r in results)


# ---- determinism and refusals -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("family", "params"),
    [
        ("noise", {"snr_db": 10.0}),
        ("tone_swap", {"index": 0, "to": "3"}),
        ("rate", {"factor": 0.9}),
    ],
)
def test_the_same_seed_gives_the_same_audio_and_another_seed_gives_other_noise(src, family, params):
    first = synth.perturb(src, family, params, 5)
    again = synth.perturb(src, family, params, 5)
    np.testing.assert_array_equal(first[0], again[0])
    assert first[1] == again[1] and first[2] == again[2]
    if family == "noise":
        assert not np.array_equal(first[0], synth.perturb(src, family, params, 6)[0])


def test_a_noise_recording_can_be_supplied_and_is_looped(src, tmp_path):
    bed = np.random.default_rng(0).standard_normal(4_000).astype(np.float32) * 0.1  # 0.25 s
    noise_wav = write_clip(tmp_path, "cafe", bed, intended=["1"]).path
    params = {"snr_db": 10.0, "noise_wav": str(tmp_path / noise_wav)}
    audio, truth, row = synth.perturb(src, "noise", params, 0)
    clean = synth.perturb(src, "identity", {}, 0)[0]
    assert len(audio) == len(src.pcm) > len(bed)
    assert row.condition.noise == "cafe 10 dB" and row.synthetic["params"] == params
    added = audio - clean
    assert np.std(added) > 0 and np.all(np.isfinite(added))
    with pytest.raises(SynthError, match="noise.*cannot read"):
        synth.perturb(src, "noise", {"snr_db": 10.0, "noise_wav": str(tmp_path / "no.wav")}, 0)


def test_output_never_exceeds_full_scale(root, pack_toml):
    loud = write_clip(root, "src-loud", 1.9 * utterance(["4", "1", "3"]), intended=["4", "1", "3"])
    source = synth.prepare(loud, root=root, pack_toml=pack_toml)
    audio, _, _ = synth.perturb(source, "noise", {"snr_db": 5.0}, 0)
    assert np.abs(audio).max() <= 0.99


def test_sources_that_would_be_mislabelled_are_refused(root, pack_toml):
    synthetic = quiet_clip(root, "already-synthetic", ["1", "2"], set="synthetic")
    with pytest.raises(SynthError, match="already-synthetic.*synthetic"):
        synth.prepare(synthetic, root=root, pack_toml=pack_toml)
    wrong = quiet_clip(root, "wrong-tones", ["1", "2"], label="tone_error")
    with pytest.raises(SynthError, match="wrong-tones.*tone_error.*correct"):
        synth.prepare(wrong, root=root, pack_toml=pack_toml)


def test_a_clip_with_nothing_to_target_is_refused_naming_it(root, pack_toml):
    silence = write_clip(root, "silent", np.zeros(RATE, dtype=np.float32), intended=["1"])
    with pytest.raises(SynthError, match="silent.*no syllable"):
        synth.prepare(silence, root=root, pack_toml=pack_toml)
    with pytest.raises(evaluate.EvalError, match="ghost.*cannot read"):
        ghost = quiet_clip(root, "ghost", ["1"])
        (root / ghost.path).unlink()
        synth.prepare(ghost, root=root, pack_toml=pack_toml)


def test_prepare_finds_a_span_for_each_syllable_and_uses_the_pack_accent(src, pack_toml):
    assert src.voice.tones == ("4", "1", "3")
    assert all(extent is not None for extent in src.voice.extents)
    starts = [e[0] for e in src.voice.extents]
    assert starts == sorted(starts)
    assert src.accent == "cmn-standard" == evaluate.base_accent(pack_toml)
    for start, end in src.voice.extents:
        assert end - start >= 5 and np.isfinite(src.voice.st[start:end]).sum() >= 5


# ---- the direction check --------------------------------------------------------------------------


def test_a_tone_swap_scores_lower_than_the_identity_resynthesis(src, pack_toml, calib_json, capsys):
    """Not a threshold, just the sign: if tonekit rates a wrong tone no lower than the same clip
    said right, the perturbation or the scoring is broken. The numbers go to the report."""
    grader = evaluate.Grader(pack_toml, calib_json, src.accent, root=Path("."), cache_dir=None)
    scores = {}
    for name, family, params in [
        ("identity", "identity", {}),
        ("tone_swap 1->4", "tone_swap", {"index": 1, "to": "4"}),
        ("tone_swap 1->2", "tone_swap", {"index": 1, "to": "2"}),
    ]:
        audio, _, row = synth.perturb(src, family, params, 0)
        result, _ = grader.grade_pcm(row, audio)
        scores[name] = result.overall
    with capsys.disabled():
        print(f"\ndirection check, overall: {scores}")
    assert scores["identity"] is not None and scores["tone_swap 1->4"] is not None
    assert scores["tone_swap 1->4"] < scores["identity"]


# ---- tkh synth ---------------------------------------------------------------------------------


def _write_corpus(root: Path) -> Path:
    clips = [
        quiet_clip(root, "cli-413", ["4", "1", "3"], pair="p1"),
        quiet_clip(root, "cli-1523", ["1", "5", "2", "3"], pair="p2"),
        quiet_clip(root, "cli-err", ["4", "2", "3"], label="tone_error"),  # never a source
        write_clip(root, "cli-register", 0.5 * utterance(["1", "2"]), intended=["1", "2"],
                   set="register", label="n/a"),  # never a source
    ]  # fmt: skip
    from support import write_manifest

    return write_manifest(root / "manifest.jsonl", clips)


def test_tkh_synth_writes_a_corpus_evaluate_can_grade(tmp_path, pack_toml, calib_json, capsys):
    src_root = tmp_path / "corpus"
    src_root.mkdir()
    manifest_path = _write_corpus(src_root)
    out = tmp_path / "synth"

    code = cli.main(
        ["synth", "--manifest", str(manifest_path), "--pack", str(PACKS / "cmn.toml"),
         "--calib", str(PACKS / "cmn.calib.json"), "--out", str(out), "--per-clip", "4",
         "--seed", "3"]
    )  # fmt: skip
    assert code == 0
    assert "8 clips" in capsys.readouterr().out  # 2 correct sources x 4

    rows = manifest.load(out / "manifest.jsonl")
    assert len(rows) == 8 and len({r.id for r in rows}) == 8
    assert {r.synthetic["from"] for r in rows} == {"cli-413", "cli-1523"}
    assert all(r.set == "synthetic" and r.source == "synthetic-world" for r in rows)
    assert all(r.synthetic["family"] in FAMILIES and r.synthetic["family"] != "identity" for r in rows)
    truth = [json.loads(line) for line in (out / "truth.jsonl").read_text().splitlines()]
    assert [t["id"] for t in truth] == [r.id for r in rows]

    results = evaluate.run(rows, pack_toml, calib_json, None, root=out, use_cache=False)
    assert [r.id for r in results] == [r.id for r in rows]

    # deterministic: the same seed writes the same corpus
    again = tmp_path / "again"
    cli.main(
        ["synth", "--manifest", str(manifest_path), "--pack", str(PACKS / "cmn.toml"),
         "--calib", str(PACKS / "cmn.calib.json"), "--out", str(again), "--per-clip", "4",
         "--seed", "3"]
    )  # fmt: skip
    assert (again / "manifest.jsonl").read_text() == (out / "manifest.jsonl").read_text()
    assert (again / "truth.jsonl").read_text() == (out / "truth.jsonl").read_text()


def test_tkh_synth_skips_an_unusable_source_with_a_warning_and_fails_when_none_is_usable(
    tmp_path, capsys
):
    from support import write_manifest

    src_root = tmp_path / "corpus"
    src_root.mkdir()
    good = quiet_clip(src_root, "good", ["4", "1", "3"])
    silent = write_clip(src_root, "silent", np.zeros(RATE, dtype=np.float32), intended=["1"])
    args = ["--pack", str(PACKS / "cmn.toml"), "--per-clip", "1", "--out", str(tmp_path / "o")]

    both = write_manifest(src_root / "both.jsonl", [silent, good])
    assert cli.main(["synth", "--manifest", str(both), *args]) == 0
    captured = capsys.readouterr()
    assert "skipping silent" in captured.err and "synthesised 1 clip from 1 source" in captured.out

    only = write_manifest(src_root / "only.jsonl", [silent])
    assert cli.main(["synth", "--manifest", str(only), *args]) == 1
    assert "error:" in capsys.readouterr().err


def test_tkh_synth_reports_errors_and_exits_non_zero(tmp_path, capsys):
    args = ["--pack", str(PACKS / "cmn.toml"), "--per-clip", "1", "--out", str(tmp_path / "o")]
    assert cli.main(["synth", "--manifest", str(tmp_path / "missing.jsonl"), *args]) == 1
    assert "error:" in capsys.readouterr().err
