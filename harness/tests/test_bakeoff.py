"""`tkh bakeoff`: pYIN against SwiftF0 on synthetic clips with f0 truth and on the S1 gate clips.
Everything runs on the numpy harmonic voice of support.py, so the numbers are plumbing checks;
what they say about the two trackers on real speech is the report's business."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import tonekit_py
from support import RATE, gate_corpus, make_clip, write_manifest

from tonekit_harness import (
    bakeoff,
    cli,
    conditions,
    corpus,
    manifest,
    pitch_metrics,
    pitch_tracks,
    provenance,
    synth,
)

REGISTER = provenance.load_register(Path(__file__).resolve().parents[2] / "data-register.csv")

GATE_PROVIDERS = ["pyin", "swift-f0"]  # what the gate grades: the whole pipeline with each
# what the synthetic section measures: swift-f0 as handed to tonekit and as tonekit ends up with it
MEASURES = ["pyin", "swift-f0", "swift-f0 (after tonekit's octave repair)"]
CONDITIONS = ["clean", "noise ~5 dB", "noise ~10 dB", "noise ~20 dB"]


def test_the_briefs_names_are_importable_from_bakeoff():
    assert bakeoff.gpe is pitch_metrics.gpe
    assert bakeoff.vde is pitch_metrics.vde
    assert bakeoff.swiftf0_track is pitch_tracks.swiftf0_track
    assert bakeoff.gpe([120.0, 100.0, None], [100.0, 130.0, 100.0]) == 0.5
    assert bakeoff.vde([120.0, 100.0, None], [100.0, 130.0, 100.0]) == pytest.approx(1 / 3)


# ---- run ---------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def synthetic_dir(src, tmp_path_factory):
    """Two clean clips and three noise clips (one per SNR bucket), as `tkh synth` writes them."""
    made = [
        synth.perturb(src, "identity", {}, 0),
        synth.perturb(src, "rate", {"factor": 1.25}, 0),
        synth.perturb(src, "noise", {"snr_db": 6.0}, 0),
        synth.perturb(src, "noise", {"snr_db": 10.0}, 0),
        synth.perturb(src, "noise", {"snr_db": 19.0}, 0),
    ]
    out = tmp_path_factory.mktemp("bakeoff-synthetic")
    corpus.write_corpus(out, made)
    return out


def expected_frames(directory) -> dict[str, tuple[int, int]]:
    """Per condition: how many clips and how many f0 frames the corpus has."""
    truth = corpus.read_truth(directory)
    out: dict[str, tuple[int, int]] = {}
    for clip in manifest.load(directory / "manifest.jsonl"):
        name = conditions.condition(clip)
        clips, frames = out.get(name, (0, 0))
        out[name] = (clips + 1, frames + len(truth[clip.id]))
    return out


def test_run_pools_frames_per_condition_and_provider(
    synthetic_dir, pack_toml, calib_json, tmp_path
):
    result = bakeoff.run(
        synthetic=synthetic_dir, pack_toml=pack_toml, calib_json=calib_json, cache_dir=tmp_path
    )
    assert result.gate is None
    assert list(result.synthetic) == CONDITIONS
    want = expected_frames(synthetic_dir)
    for name, group in result.synthetic.items():
        assert group.clips == want[name][0]
        assert list(group.counts) == MEASURES
        for measure in MEASURES:
            assert group.counts[measure].frames == want[name][1]
    assert result.synthetic["clean"].clips == 2


def test_every_measurement_tracks_clean_resynthesised_speech_closely(
    synthetic_dir, pack_toml, calib_json, tmp_path
):
    """A wiring check: tracks compared with the wrong truth (or a shifted one) would be far off."""
    clean = bakeoff.run(
        synthetic=synthetic_dir, pack_toml=pack_toml, calib_json=calib_json, cache_dir=tmp_path
    ).synthetic["clean"]
    for measure in MEASURES:
        counts = clean.counts[measure]
        assert counts.both_voiced > 0.25 * counts.frames  # a good part of each clip is speech
        assert counts.gpe is not None and counts.gpe < 0.05, measure
        assert counts.vde is not None and counts.vde < 0.3, measure


def test_the_swiftf0_rows_are_its_track_as_handed_to_tonekit_and_the_f0_tonekit_ends_up_with(
    src, tmp_path, pack_toml, calib_json
):
    audio, truth, _ = made = synth.perturb(src, "noise", {"snr_db": 10.0}, 0)
    corpus.write_corpus(tmp_path, [made])
    got = bakeoff.run(
        synthetic=tmp_path, pack_toml=pack_toml, calib_json=calib_json, use_cache=False
    ).synthetic["noise ~10 dB"]
    f0_json = pitch_tracks.swiftf0_track(audio)
    repaired = tonekit_py.analyze(audio, RATE, None, f0_json)
    assert got.counts["pyin"] == pitch_metrics.count(
        pitch_tracks.pyin_track(tonekit_py.analyze(audio, RATE)), truth
    )
    assert got.counts["swift-f0"] == pitch_metrics.count(pitch_tracks.track_hz(f0_json), truth)
    assert got.counts[MEASURES[2]] == pitch_metrics.count(pitch_tracks.pyin_track(repaired), truth)


def gate_run(tmp_path, pack_toml, calib_json, *, source="synthetic-world", **kw):
    root = tmp_path / "gate"
    write_manifest(root / "manifest.jsonl", gate_corpus(root, source=source))
    return bakeoff.run(
        gate=root / "manifest.jsonl", pack_toml=pack_toml, calib_json=calib_json,
        cache_dir=tmp_path / "cache", register=REGISTER, **kw,
    )  # fmt: skip


def test_run_grades_the_gate_with_each_provider(tmp_path, pack_toml, calib_json):
    result = gate_run(tmp_path, pack_toml, calib_json, source="dj-corpus")
    assert result.synthetic is None
    assert list(result.gate) == GATE_PROVIDERS
    for scores in result.gate.values():
        assert len(scores.metrics.thresholds) == 2
        assert scores.candidate_id is None and scores.n_minimal == 0  # no diag_minimal clips
    assert result.clearance.verdict


def test_a_gate_over_synthetic_clips_is_not_a_gate_unless_it_is_a_smoke_run(
    tmp_path, pack_toml, calib_json
):
    refused = gate_run(tmp_path, pack_toml, calib_json)
    assert (refused.clearance.mode, refused.clearance.uncleared) == ("not a gate", 4)
    smoke = gate_run(tmp_path, pack_toml, calib_json, allow_synthetic=True)
    assert (smoke.clearance.mode, smoke.clearance.uncleared) == ("smoke", 4)


def test_a_gate_run_needs_the_data_register(tmp_path, pack_toml, calib_json):
    root = tmp_path / "gate"
    write_manifest(root / "manifest.jsonl", gate_corpus(root))
    with pytest.raises(bakeoff.BakeoffError, match="data register"):
        bakeoff.run(gate=root / "manifest.jsonl", pack_toml=pack_toml, calib_json=calib_json)


def test_a_gate_source_that_is_not_a_register_id_is_an_error(tmp_path, pack_toml, calib_json):
    with pytest.raises(manifest.ManifestError, match="source 'dj-corpu' is not an id"):
        gate_run(tmp_path, pack_toml, calib_json, source="dj-corpu")


def test_synthetic_rows_mixed_into_a_gate_manifest_are_an_error(tmp_path, pack_toml, calib_json):
    root = tmp_path / "gate"
    clips = gate_corpus(root)
    extra = make_clip(root, "extra", ["4", "1", "3"], set="synthetic", label="correct")
    write_manifest(root / "manifest.jsonl", [*clips, extra])
    with pytest.raises(manifest.ManifestError, match="mixed with gate clips"):
        bakeoff.run(
            gate=root / "manifest.jsonl", pack_toml=pack_toml, calib_json=calib_json,
            register=REGISTER, allow_synthetic=True,
        )  # fmt: skip


def test_a_synthetic_directory_without_clips_is_an_error(tmp_path, pack_toml):
    (tmp_path / "manifest.jsonl").write_text("")
    with pytest.raises(bakeoff.BakeoffError, match="has no clips"):
        bakeoff.run(synthetic=tmp_path, pack_toml=pack_toml, calib_json=None, use_cache=False)


def test_run_needs_something_to_run(pack_toml):
    with pytest.raises(bakeoff.BakeoffError, match=r"--synthetic and/or --gate"):
        bakeoff.run(pack_toml=pack_toml, calib_json=None)


def test_a_synthetic_directory_without_a_manifest_is_an_error_naming_it(tmp_path, pack_toml):
    with pytest.raises(OSError, match="manifest.jsonl"):
        bakeoff.run(synthetic=tmp_path, pack_toml=pack_toml, calib_json=None)


def test_a_clip_without_truth_is_an_error_naming_it(src, tmp_path, pack_toml, calib_json):
    made = [synth.perturb(src, "identity", {}, 0), synth.perturb(src, "rate", {"factor": 1.1}, 0)]
    corpus.write_corpus(tmp_path, made)
    lines = (tmp_path / "truth.jsonl").read_text().splitlines()
    (tmp_path / "truth.jsonl").write_text(lines[0] + "\n")
    with pytest.raises(bakeoff.BakeoffError, match=rf"{made[1][2].id}: no f0 truth"):
        bakeoff.run(synthetic=tmp_path, pack_toml=pack_toml, calib_json=calib_json, use_cache=False)


def test_truth_of_the_wrong_length_is_an_error_naming_the_clip(
    src, tmp_path, pack_toml, calib_json
):
    made = synth.perturb(src, "identity", {}, 0)
    corpus.write_corpus(tmp_path, [made])
    (tmp_path / "truth.jsonl").write_text(
        json.dumps({"id": made[2].id, "f0_hz": [100.0] * 5}) + "\n"
    )
    with pytest.raises(bakeoff.BakeoffError, match=rf"{made[2].id}: .*frames"):
        bakeoff.run(synthetic=tmp_path, pack_toml=pack_toml, calib_json=calib_json, use_cache=False)


# ---- tkh bakeoff -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cli_run(tmp_path_factory, pack_toml, calib_json):
    """`tkh synth` on the two correct clips of a support gate corpus, then `tkh bakeoff` on that
    output and on the gate corpus itself."""
    root = tmp_path_factory.mktemp("bakeoff-cli")
    gate = write_manifest(root / "gate" / "manifest.jsonl", gate_corpus(root / "gate"))
    pack = root / "cmn.toml"
    pack.write_text(pack_toml, encoding="utf-8")
    calib = root / "cmn.calib.json"
    calib.write_text(calib_json, encoding="utf-8")
    common = ["--pack", str(pack), "--calib", str(calib)]
    assert cli.main(["synth", "--manifest", str(gate), *common, "--out", str(root / "synth"),
                     "--per-clip", "2", "--seed", "1"]) == 0  # fmt: skip
    report = root / "reports" / "p0-bakeoff.md"
    argv = ["bakeoff", "--synthetic", str(root / "synth"), "--gate", str(gate), *common,
            "--report", str(report), "--no-cache", "--allow-synthetic"]  # fmt: skip
    return root, argv, report


def test_tkh_bakeoff_writes_a_report_with_both_sections(cli_run, capsys):
    root, argv, report = cli_run
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "bakeoff:" in out and str(report) in out
    text = report.read_text(encoding="utf-8")
    assert text.startswith("# P0 f0 bakeoff: pYIN against SwiftF0\n")
    synthetic = text.split("## Synthetic f0 accuracy")[1].split("## Gate S1")[0]
    gate = text.split("## Gate S1")[1]
    for section in (synthetic, gate):
        assert "pyin" in section and "swift-f0" in section
    assert "S1 (leave-one-pair-out): SMOKE (synthetic)" in gate  # synthetic clips: no PASS or FAIL
    assert "PASS" not in gate and "FAIL" not in gate
    assert "- data register: " in text
    assert "Lower GPE, by condition:" in synthetic and "Lower VDE, by condition:" in synthetic
    assert "swift-f0 (after tonekit's octave repair)" in synthetic


def test_the_synthetic_table_accounts_for_every_frame_of_every_clip(cli_run):
    root, argv, report = cli_run
    assert cli.main(argv) == 0
    section = report.read_text(encoding="utf-8").split("## Synthetic f0 accuracy")[1]
    section = section.split("## Gate S1")[0]
    total = sum(len(f0) for f0 in corpus.read_truth(root / "synth").values())
    cells = [
        [c.strip() for c in line.strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("|")
    ]
    for measure in MEASURES:
        frames = [
            int(c[3]) for c in cells if c[2] == measure
        ]  # Condition | Clips | Provider | Frames
        assert sum(frames) == total, measure


def test_the_report_is_the_same_on_a_rerun(cli_run):
    root, argv, report = cli_run
    assert cli.main(argv) == 0
    first = report.read_text(encoding="utf-8")
    assert cli.main(argv) == 0
    assert report.read_text(encoding="utf-8") == first


def without(argv: list[str], flag: str, report: str) -> list[str]:
    """`argv` minus `flag` and its value (a bare flag has none), writing to `report` instead."""
    i = argv.index(flag)
    rest = argv[:i] + argv[i + (1 if flag == "--allow-synthetic" else 2) :]
    rest[rest.index("--report") + 1] = report
    return rest


def test_a_gate_over_synthetic_clips_is_not_a_gate_without_allow_synthetic(
    cli_run, tmp_path, capsys
):
    root, argv, _ = cli_run
    out = tmp_path / "refused.md"
    assert cli.main(without(argv, "--allow-synthetic", str(out))) == 0
    gate = out.read_text(encoding="utf-8").split("## Gate S1")[1]
    assert "NOT A GATE (4 synthetic / non-allowed clips)" in gate
    assert "PASS" not in gate and "FAIL" not in gate
    summary = capsys.readouterr().out
    assert "S1: NOT A GATE (4 synthetic / non-allowed clips)" in summary
    assert "PASS" not in summary and "FAIL" not in summary


def test_the_summary_line_of_a_smoke_run_has_no_verdict(cli_run, capsys):
    _, argv, _ = cli_run
    assert cli.main(argv) == 0
    summary = capsys.readouterr().out
    assert "S1: SMOKE (synthetic)" in summary and "PASS" not in summary and "FAIL" not in summary


def test_a_missing_register_is_an_error_for_a_gate_run(cli_run, tmp_path, capsys):
    _, argv, _ = cli_run
    out = tmp_path / "r.md"
    assert cli.main([*without(argv, "--synthetic", str(out)), "--register", str(tmp_path / "no.csv")]) == 1
    assert "no.csv" in capsys.readouterr().err and not out.exists()


def test_synthetic_only_and_gate_only_runs_write_only_their_section(cli_run, tmp_path):
    root, argv, _ = cli_run
    for flag in ("--gate", "--synthetic"):
        out = tmp_path / f"without{flag}.md"
        assert cli.main(without(argv, flag, str(out))) == 0
    no_gate = (tmp_path / "without--gate.md").read_text(encoding="utf-8")
    assert "## Synthetic f0 accuracy" in no_gate and "## Gate S1" not in no_gate
    no_synthetic = (tmp_path / "without--synthetic.md").read_text(encoding="utf-8")
    assert "## Gate S1" in no_synthetic and "## Synthetic f0 accuracy" not in no_synthetic


class BrokenDetector:
    """What onnxruntime does when it fails: an error that is not a ValueError."""

    def detect(self, *args, **kwargs):
        raise RuntimeError("onnx exploded")


@pytest.mark.parametrize("dropped", ["--gate", "--synthetic"])
def test_a_detector_failure_is_an_error_naming_the_clip_not_a_traceback(
    cli_run, monkeypatch, capsys, tmp_path, dropped
):
    root, argv, _ = cli_run
    monkeypatch.setattr(pitch_tracks, "_detector", lambda: BrokenDetector())
    out = tmp_path / "r.md"
    assert cli.main(without(argv, dropped, str(out))) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "RuntimeError: onnx exploded" in err
    assert "gate-0" in err  # the clip's id: gate clips and the synthetic clips made from them
    assert not out.exists()


def test_a_gate_that_fails_s1_is_still_exit_zero(tmp_path, pack_toml):
    """The two clips of the only pairs are the same audio, so no threshold can separate them."""
    clips = [
        make_clip(
            tmp_path, f"g{i}-{label}", ["4", "1", "3"], pair=f"g{i}", label=label, source="dj-corpus"
        )
        for i in (1, 2)
        for label in ("correct", "tone_error")
    ]
    gate = write_manifest(tmp_path / "manifest.jsonl", clips)
    (tmp_path / "cmn.toml").write_text(pack_toml, encoding="utf-8")
    argv = ["bakeoff", "--gate", str(gate), "--pack", str(tmp_path / "cmn.toml"),
            "--report", str(tmp_path / "r.md"), "--no-cache"]  # fmt: skip
    assert cli.main(argv) == 0
    assert "FAIL" in (tmp_path / "r.md").read_text(encoding="utf-8")


def test_neither_synthetic_nor_gate_is_an_error_and_writes_nothing(tmp_path, capsys):
    report = tmp_path / "r.md"
    assert cli.main(["bakeoff", "--pack", "p.toml", "--report", str(report)]) == 1
    assert "error: give --synthetic and/or --gate" in capsys.readouterr().err
    assert not report.exists()


@pytest.mark.parametrize("flag", ["--synthetic", "--gate"])
def test_a_missing_input_is_an_error_and_exit_one(tmp_path, capsys, pack_toml, flag):
    (tmp_path / "cmn.toml").write_text(pack_toml, encoding="utf-8")
    argv = ["bakeoff", flag, str(tmp_path / "nowhere"), "--pack", str(tmp_path / "cmn.toml"),
            "--report", str(tmp_path / "r.md")]  # fmt: skip
    assert cli.main(argv) == 1
    assert capsys.readouterr().err.startswith("error: ")
    assert not (tmp_path / "r.md").exists()


def test_the_bakeoff_command_documents_its_flags(capsys):
    with pytest.raises(SystemExit) as stop:
        cli.main(["bakeoff", "--help"])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    for flag in (
        "--synthetic",
        "--gate",
        "--pack",
        "--calib",
        "--accent",
        "--report",
        "--register",
        "--allow-synthetic",
        "--no-cache",
    ):
        assert flag in out
