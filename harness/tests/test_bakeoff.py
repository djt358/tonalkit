"""`tkh bakeoff`: pYIN against SwiftF0 on synthetic clips with f0 truth and on the S1 gate clips.
Everything runs on the numpy harmonic voice of support.py, so the numbers are plumbing checks;
what they say about the two trackers on real speech is the report's business."""

from __future__ import annotations

import json

import pytest
from support import candidate, gate_corpus, make_clip, write_manifest

from tonekit_harness import bakeoff, cli, corpus, manifest, pitch_metrics, pitch_tracks, synth
from tonekit_harness.manifest import Clip, Condition

PROVIDERS = ["pyin", "swift-f0"]
CONDITIONS = ["clean", "noise ~5 dB", "noise ~10 dB", "noise ~20 dB"]


def row(family: str | None, params: dict | None = None, noise: str = "none") -> Clip:
    """A manifest row with only what `bakeoff.condition` looks at."""
    synthetic = None if family is None else {"family": family, "params": params or {}}
    return Clip(
        id="c", path="c.wav", speaker="s", set="synthetic", label="correct",
        intended=candidate(["1"]), condition=Condition(noise=noise, distance="synthetic"),
        source="synthetic-world", synthetic=synthetic,
    )  # fmt: skip


def test_the_briefs_names_are_importable_from_bakeoff():
    assert bakeoff.gpe is pitch_metrics.gpe
    assert bakeoff.vde is pitch_metrics.vde
    assert bakeoff.swiftf0_track is pitch_tracks.swiftf0_track
    assert bakeoff.gpe([120.0, 100.0, None], [100.0, 130.0, 100.0]) == 0.5
    assert bakeoff.vde([120.0, 100.0, None], [100.0, 130.0, 100.0]) == pytest.approx(1 / 3)


# ---- conditions --------------------------------------------------------------------------------


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
    assert bakeoff.condition(clip) == want


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
        clips, frames = out.get(bakeoff.condition(clip), (0, 0))
        out[bakeoff.condition(clip)] = (clips + 1, frames + len(truth[clip.id]))
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
        assert list(group.counts) == PROVIDERS
        for provider in PROVIDERS:
            assert group.counts[provider].frames == want[name][1]
    assert result.synthetic["clean"].clips == 2


def test_both_providers_track_clean_resynthesised_speech_closely(
    synthetic_dir, pack_toml, calib_json, tmp_path
):
    """A wiring check: tracks compared with the wrong truth (or a shifted one) would be far off."""
    clean = bakeoff.run(
        synthetic=synthetic_dir, pack_toml=pack_toml, calib_json=calib_json, cache_dir=tmp_path
    ).synthetic["clean"]
    for provider in PROVIDERS:
        counts = clean.counts[provider]
        assert counts.both_voiced > 0.25 * counts.frames  # a good part of each clip is speech
        assert counts.gpe is not None and counts.gpe < 0.05, provider
        assert counts.vde is not None and counts.vde < 0.3, provider


def test_run_grades_the_gate_with_each_provider(tmp_path, pack_toml, calib_json):
    root = tmp_path / "gate"
    write_manifest(root / "manifest.jsonl", gate_corpus(root))
    result = bakeoff.run(
        gate=root / "manifest.jsonl", pack_toml=pack_toml, calib_json=calib_json,
        cache_dir=tmp_path / "cache",
    )  # fmt: skip
    assert result.synthetic is None
    assert list(result.gate) == PROVIDERS
    for scores in result.gate.values():
        assert len(scores.metrics.thresholds) == 2
        assert scores.candidate_id is None and scores.n_minimal == 0  # no diag_minimal clips


def test_the_noise_buckets_are_the_ones_the_report_describes():
    assert bakeoff.NOISE_BUCKETS_DB == (5.0, 10.0, 20.0)  # bakeoff_report's text says so


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
            "--report", str(report), "--no-cache"]  # fmt: skip
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
    assert "S1 (leave-one-pair-out): pyin " in gate and "swift-f0 " in gate
    assert "Lower GPE, by condition:" in synthetic


def test_the_synthetic_table_accounts_for_every_frame_of_every_clip(cli_run):
    root, argv, report = cli_run
    assert cli.main(argv) == 0
    section = report.read_text(encoding="utf-8").split("## Synthetic f0 accuracy")[1]
    section = section.split("## Gate S1")[0]
    total = sum(len(f0) for f0 in corpus.read_truth(root / "synth").values())
    for provider in PROVIDERS:
        cells = [
            [c.strip() for c in line.strip("|").split("|")]
            for line in section.splitlines()
            if line.startswith("|")
        ]
        frames = [
            int(c[3]) for c in cells if c[2] == provider
        ]  # Condition | Clips | Provider | Frames
        assert sum(frames) == total, provider


def test_the_report_is_the_same_on_a_rerun(cli_run):
    root, argv, report = cli_run
    assert cli.main(argv) == 0
    first = report.read_text(encoding="utf-8")
    assert cli.main(argv) == 0
    assert report.read_text(encoding="utf-8") == first


def test_synthetic_only_and_gate_only_runs_write_only_their_section(cli_run, tmp_path):
    root, argv, _ = cli_run

    def run_without(flag: str) -> str:
        i = argv.index(flag)
        rest = argv[:i] + argv[i + 2 :]
        out = tmp_path / f"without{flag}.md"
        rest[rest.index("--report") + 1] = str(out)
        assert cli.main(rest) == 0
        return out.read_text(encoding="utf-8")

    no_gate = run_without("--gate")
    assert "## Synthetic f0 accuracy" in no_gate and "## Gate S1" not in no_gate
    no_synthetic = run_without("--synthetic")
    assert "## Gate S1" in no_synthetic and "## Synthetic f0 accuracy" not in no_synthetic


def test_a_gate_that_fails_s1_is_still_exit_zero(tmp_path, pack_toml):
    """The two clips of the only pairs are the same audio, so no threshold can separate them."""
    clips = [
        make_clip(tmp_path, f"g{i}-{label}", ["4", "1", "3"], pair=f"g{i}", label=label)
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
        "--no-cache",
    ):
        assert flag in out
