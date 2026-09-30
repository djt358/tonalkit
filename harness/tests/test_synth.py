"""`synth.perturb` and `tkh synth`: what a perturbed clip is (audio, ground-truth f0, manifest row),
determinism, refusals, and the direction check that asks tonekit itself. The families' effects are
in test_family_effects.py, the source in test_source.py, the files written in test_corpus.py."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest
from support import RATE, utterance, write_clip, write_manifest
from synth_support import HOP, PACKS, quiet_clip, semitones

from tonekit_harness import cli, evaluate, manifest, source, synth
from tonekit_harness.families import FAMILIES
from tonekit_harness.family import SynthError

# ---- the brief's checks --------------------------------------------------------------------------


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


# ---- the manifest rows ---------------------------------------------------------------------------


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


# ---- determinism and refusals --------------------------------------------------------------------


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
    loud_src = source.prepare(loud, root=root, pack_toml=pack_toml)
    audio, _, _ = synth.perturb(loud_src, "noise", {"snr_db": 5.0}, 0)
    assert np.abs(audio).max() <= 0.99


# ---- the direction check -------------------------------------------------------------------------


def test_a_tone_swap_scores_lower_than_the_identity_resynthesis(
    src, pack_toml, calib_json, record_property
):
    """Not a threshold, just the sign: if tonekit rates a wrong tone no lower than the same clip
    said right, the perturbation or the scoring is broken. The scores are recorded as the
    test's `overall` property (`-o junit_family=xunit1 --junitxml=...`), for the task report."""
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
    record_property("overall", json.dumps(scores))
    assert scores["identity"] is not None and scores["tone_swap 1->4"] is not None
    assert scores["tone_swap 1->4"] < scores["identity"]


# ---- tkh synth -----------------------------------------------------------------------------------


def _write_corpus(root: Path) -> Path:
    clips = [
        quiet_clip(root, "cli-413", ["4", "1", "3"], pair="p1"),
        quiet_clip(root, "cli-1523", ["1", "5", "2", "3"], pair="p2"),
        quiet_clip(root, "cli-err", ["4", "2", "3"], label="tone_error"),  # never a source
        write_clip(root, "cli-register", 0.5 * utterance(["1", "2"]), intended=["1", "2"],
                   set="register", label="n/a"),  # never a source
    ]  # fmt: skip
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
    assert "8 clips from 2 sources (0 skipped)" in capsys.readouterr().out  # 2 correct sources x 4

    rows = manifest.load(out / "manifest.jsonl")
    assert len(rows) == 8 and len({r.id for r in rows}) == 8
    assert {r.synthetic["from"] for r in rows} == {"cli-413", "cli-1523"}
    assert all(r.set == "synthetic" and r.source == "synthetic-world" for r in rows)
    used = {r.synthetic["family"] for r in rows}
    assert used <= set(FAMILIES) - {"identity"}
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
    src_root = tmp_path / "corpus"
    src_root.mkdir()
    good = quiet_clip(src_root, "good", ["4", "1", "3"])
    silent = write_clip(src_root, "silent", np.zeros(RATE, dtype=np.float32), intended=["1"])
    args = ["--pack", str(PACKS / "cmn.toml"), "--per-clip", "1", "--out", str(tmp_path / "o")]

    both = write_manifest(src_root / "both.jsonl", [silent, good])
    assert cli.main(["synth", "--manifest", str(both), *args]) == 0
    captured = capsys.readouterr()
    assert "skipping silent" in captured.err
    assert "synthesised 1 clip from 1 source (1 skipped); written to" in captured.out

    only = write_manifest(src_root / "only.jsonl", [silent])
    assert cli.main(["synth", "--manifest", str(only), *args]) == 1
    assert "error:" in capsys.readouterr().err


def test_tkh_synth_reports_errors_and_exits_non_zero(tmp_path, capsys):
    args = ["--pack", str(PACKS / "cmn.toml"), "--per-clip", "1", "--out", str(tmp_path / "o")]
    assert cli.main(["synth", "--manifest", str(tmp_path / "missing.jsonl"), *args]) == 1
    assert "error:" in capsys.readouterr().err
