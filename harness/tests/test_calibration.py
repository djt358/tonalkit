"""Which calibration the harness grades with: `--calib`, else the `<pack stem>.calib.json` beside
the pack (as the tonekit CLI does), else tonekit's compiled-in default; and that every report says
exactly what it used."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import tonekit_py
from support import gate_corpus, write_manifest
from synth_support import quiet_clip

from tonekit_harness import calibration, cli, evaluate, source

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture
def pack_dir(tmp_path) -> Path:
    """A copy of the cmn pack whose calibration differs from tonekit's compiled-in default, so
    that a command that does not read it is visibly grading with something else."""
    d = tmp_path / "packs"
    d.mkdir()
    (d / "cmn.toml").write_text((PACKS / "cmn.toml").read_text(encoding="utf-8"), encoding="utf-8")
    calib = json.loads((PACKS / "cmn.calib.json").read_text(encoding="utf-8"))
    calib["temperature"] = 2.0
    (d / "cmn.calib.json").write_text(json.dumps(calib), encoding="utf-8")
    return d


# ---- load ---------------------------------------------------------------------------------------


def test_the_calibration_beside_the_pack_is_used_when_none_is_named(pack_dir):
    files = calibration.load(pack_dir / "cmn.toml", None)
    sibling = (pack_dir / "cmn.calib.json").read_text(encoding="utf-8")
    assert files.calib_json == sibling and files.calib_path == pack_dir / "cmn.calib.json"
    assert files.pack_toml == (pack_dir / "cmn.toml").read_text(encoding="utf-8")


def test_an_explicit_calibration_wins_over_the_one_beside_the_pack(pack_dir, tmp_path):
    other = tmp_path / "other.json"
    other.write_text('{"temperature": 3.0}', encoding="utf-8")
    files = calibration.load(pack_dir / "cmn.toml", other)
    assert files.calib_json == '{"temperature": 3.0}' and files.calib_path == other


def test_without_either_the_compiled_in_default_is_used(tmp_path):
    (tmp_path / "x.toml").write_text("[pack]\n", encoding="utf-8")
    files = calibration.load(tmp_path / "x.toml", None)
    assert files.calib_json is None and files.calib_path is None


def test_the_sibling_is_the_pack_stem_with_calib_json_like_the_cli_makes_it(tmp_path):
    for pack, sibling in (
        ("cmn.toml", "cmn.calib.json"),
        ("a.b.toml", "a.b.calib.json"),  # only the last extension is replaced
        ("cmn", "cmn.calib.json"),  # no extension: one is added
    ):
        (tmp_path / pack).write_text("[pack]\n", encoding="utf-8")
        (tmp_path / sibling).write_text('{"temperature": 1.5}', encoding="utf-8")
        assert calibration.load(tmp_path / pack, None).calib_path == tmp_path / sibling


def test_a_directory_named_like_the_sibling_is_not_a_calibration(tmp_path):
    (tmp_path / "x.toml").write_text("[pack]\n", encoding="utf-8")
    (tmp_path / "x.calib.json").mkdir()  # the CLI asks for a file
    assert calibration.load(tmp_path / "x.toml", None).calib_json is None


def test_a_missing_explicit_calibration_is_an_error_naming_it(pack_dir, tmp_path):
    with pytest.raises(OSError, match="nowhere.json"):
        calibration.load(pack_dir / "cmn.toml", tmp_path / "nowhere.json")


def test_a_missing_pack_is_an_error_naming_it(tmp_path):
    with pytest.raises(OSError, match="gone.toml"):
        calibration.load(tmp_path / "gone.toml", None)


# ---- what a report says it used -------------------------------------------------------------


def test_the_context_records_the_hashes_of_the_files_actually_read(pack_dir, tmp_path):
    files = calibration.load(pack_dir / "cmn.toml", None)
    context = files.context()
    pack_text = (pack_dir / "cmn.toml").read_text(encoding="utf-8")
    calib_text = (pack_dir / "cmn.calib.json").read_text(encoding="utf-8")
    assert context["pack"] == f"{pack_dir / 'cmn.toml'} (sha256 {sha(pack_text)})"
    assert context["calibration"] == (
        f"{pack_dir / 'cmn.calib.json'} (beside the pack; sha256 {sha(calib_text)})"
    )
    named = calibration.load(pack_dir / "cmn.toml", pack_dir / "cmn.calib.json").context()
    assert named["calibration"].endswith(f"(--calib; sha256 {sha(calib_text)})")


def test_the_context_says_when_the_compiled_in_default_was_used(tmp_path):
    (tmp_path / "x.toml").write_text("[pack]\n", encoding="utf-8")
    text = calibration.load(tmp_path / "x.toml", None).context()["calibration"]
    assert "compiled-in default" in text and str(tmp_path / "x.calib.json") in text


def test_the_hash_is_of_the_bytes_on_disk_not_of_the_decoded_text(tmp_path):
    (tmp_path / "x.toml").write_bytes(b"[pack]\r\nname = 'x'\r\n")  # CRLF survives
    files = calibration.load(tmp_path / "x.toml", None)
    assert files.pack_sha256 == hashlib.sha256(b"[pack]\r\nname = 'x'\r\n").hexdigest()


# ---- the commands use it --------------------------------------------------------------------


@pytest.fixture
def seen(monkeypatch) -> list[str | None]:
    """The calibration JSON of every `tonekit_py.assess` call."""
    calls: list[str | None] = []
    real = tonekit_py.assess

    def spy(analysis_json, pack, calib, request_json):
        calls.append(calib)
        return real(analysis_json, pack, calib, request_json)

    monkeypatch.setattr(evaluate.tonekit_py, "assess", spy)
    return calls


def corpus_args(pack_dir, tmp_path, *extra):
    root = tmp_path / "corpus"
    write_manifest(root / "manifest.jsonl", gate_corpus(root))
    return [
        "--manifest", str(root / "manifest.jsonl"),
        "--pack", str(pack_dir / "cmn.toml"),
        "--report", str(tmp_path / "report.md"),
        "--no-cache", *extra,
    ]  # fmt: skip


def test_tkh_eval_without_calib_grades_with_the_calibration_beside_the_pack(
    pack_dir, tmp_path, seen
):
    assert cli.main(["eval", *corpus_args(pack_dir, tmp_path, "--allow-synthetic")]) == 0
    sibling = (pack_dir / "cmn.calib.json").read_text(encoding="utf-8")
    assert seen and set(seen) == {sibling}


def test_tkh_eval_reports_the_pack_the_calibration_and_the_build_it_used(pack_dir, tmp_path, seen):
    assert cli.main(["eval", *corpus_args(pack_dir, tmp_path, "--allow-synthetic")]) == 0
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    pack_text = (pack_dir / "cmn.toml").read_text(encoding="utf-8")
    calib_text = (pack_dir / "cmn.calib.json").read_text(encoding="utf-8")
    assert f"sha256 {sha(pack_text)}" in text
    assert f"(beside the pack; sha256 {sha(calib_text)})" in text
    assert f"- tonekit-py: {evaluate.tonekit_py_fingerprint()}" in text
    assert "+" in evaluate.tonekit_py_fingerprint()  # the version and a hash of the extension


def test_tkh_bakeoff_without_calib_grades_with_the_calibration_beside_the_pack(
    pack_dir, tmp_path, seen
):
    args = corpus_args(pack_dir, tmp_path, "--allow-synthetic")
    args[args.index("--manifest")] = "--gate"
    assert cli.main(["bakeoff", *args]) == 0
    sibling = (pack_dir / "cmn.calib.json").read_text(encoding="utf-8")
    assert seen and set(seen) == {sibling}
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    pack_text = (pack_dir / "cmn.toml").read_text(encoding="utf-8")
    calib_text = (pack_dir / "cmn.calib.json").read_text(encoding="utf-8")
    assert f"sha256 {sha(pack_text)}" in text
    assert f"(beside the pack; sha256 {sha(calib_text)})" in text
    assert f"- tonekit-py: {evaluate.tonekit_py_fingerprint()}" in text


def test_load_sources_without_calib_uses_the_calibration_beside_the_pack(pack_dir, tmp_path):
    clip = quiet_clip(tmp_path, "gen-0", ["4", "1", "3"])
    manifest_path = write_manifest(tmp_path / "manifest.jsonl", [clip])
    (src,) = source.load_sources(manifest_path, pack_dir / "cmn.toml", None, None)
    assert src.calib_json == (pack_dir / "cmn.calib.json").read_text(encoding="utf-8")


def test_the_calib_flags_say_what_the_default_is(capsys):
    for command in ("eval", "bakeoff", "synth", "adversary"):
        with pytest.raises(SystemExit):
            cli.main([command, "--help"])
        help_text = " ".join(capsys.readouterr().out.split())
        assert "beside the pack" in help_text, command
