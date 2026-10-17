"""`tkh corpora`: one row per corpus, and `--data DIR` (before or after the command) choosing the
data root."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from registry_support import add_corpus, build_composed_root, speaker, speaker_clips

from tonekit_harness import cli
from tonekit_harness.registry import DataRoot


@pytest.fixture
def root(tmp_path):
    return build_composed_root(tmp_path)


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def table(out: str) -> list[list[str]]:
    """The rows of the table: cells split on runs of two or more spaces."""
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("corpus "))
    rows = []
    for line in lines[start:]:
        if line.startswith(("stale:", "error:")):
            break
        rows.append(re.split(r"\s{2,}", line.strip()))
    return rows


def test_it_lists_every_corpus_with_kind_source_speakers_clips_and_stale(root, capsys):
    code, out, err = run(capsys, "--data", str(root), "corpora")
    assert code == 0 and err == ""
    assert out.splitlines()[0] == f"data root: {root}"
    assert table(out) == [
        ["corpus", "kind", "source", "speakers", "clips", "stale"],
        ["aishell3", "public", "aishell-3", "dev 1, calib 1, heldout 1", "gate 6", "no"],
        ["dj-2026-10", "recorded", "dj-corpus", "gate 1", "gate 2", "no"],
        ["smoke", "synthetic", "synthetic-world", "calib 1", "synthetic 2", "no"],
        ["volunteers-2026-10", "recorded", "volunteer-corpus", "gate 2", "gate 4, register 2", "no"],
    ]


def test_a_stale_corpus_is_flagged_and_its_reasons_follow_the_table(root, capsys):
    data = DataRoot(root)
    data.mark_stale("volunteers-2026-10", "session purged")
    data.mark_stale("volunteers-2026-10", "calibration refitted")
    _, out, _ = run(capsys, "--data", str(root), "corpora")
    rows = {r[0]: r for r in table(out)}
    assert rows["volunteers-2026-10"][-1] == "STALE" and rows["dj-2026-10"][-1] == "no"
    assert "stale: volunteers-2026-10: session purged; calibration refitted" in out.splitlines()


def test_clearing_the_marker_clears_the_flag(root, capsys):
    data = DataRoot(root)
    data.mark_stale("dj-2026-10", "x")
    data.clear_stale("dj-2026-10", marked_before=datetime.now(UTC) + timedelta(seconds=1))
    _, out, _ = run(capsys, "--data", str(root), "corpora")
    assert "STALE" not in out and "stale:" not in out


def test_a_corpus_with_no_speakers_or_clips_yet_shows_dashes(tmp_path, capsys):
    add_corpus(tmp_path, "fresh", kind="recorded", source="volunteer-corpus", speakers=[], clips=[])
    _, out, _ = run(capsys, "--data", str(tmp_path), "corpora")
    assert table(out)[1] == ["fresh", "recorded", "volunteer-corpus", "-", "-", "no"]


def test_the_data_root_comes_from_the_environment_without_the_flag(root, monkeypatch, capsys):
    monkeypatch.setenv("TONEKIT_DATA", str(root))
    code, out, _ = run(capsys, "corpora")
    assert code == 0 and f"data root: {root}" in out


def test_the_flag_beats_the_environment(root, tmp_path_factory, monkeypatch, capsys):
    other = tmp_path_factory.mktemp("other")
    add_corpus(other, "only-here", kind="recorded", source="dj-corpus", speakers=[speaker("dj")],
               clips=speaker_clips("dj", "dj-corpus"))  # fmt: skip
    monkeypatch.setenv("TONEKIT_DATA", str(root))
    _, out, _ = run(capsys, "--data", str(other), "corpora")
    assert [r[0] for r in table(out)[1:]] == ["only-here"]


def test_a_root_without_corpora_says_so(tmp_path, capsys):
    code, out, err = run(capsys, "--data", str(tmp_path), "corpora")
    assert code == 0 and err == ""
    assert out.splitlines() == [f"data root: {tmp_path}", f"no corpora under {tmp_path / 'corpora'}"]


def test_a_root_that_does_not_exist_is_an_error(tmp_path, capsys):
    code, out, err = run(capsys, "--data", str(tmp_path / "typo"), "corpora")
    assert code == 1 and out == ""
    assert err == f"error: the data root {tmp_path / 'typo'} does not exist (set TONEKIT_DATA or pass --data)\n"


def test_a_broken_corpus_is_listed_with_its_error_and_the_rest_still_show(root, capsys):
    (root / "corpora" / "aishell3" / "manifest.jsonl").write_text("{broken\n", encoding="utf-8")
    (root / "corpora" / "dj-2026-10" / "corpus.toml").write_text("[corpus\n", encoding="utf-8")
    code, out, err = run(capsys, "--data", str(root), "corpora")
    assert code == 1
    rows = {r[0]: r for r in table(out)}
    assert rows["aishell3"] == ["aishell3", "public", "aishell-3", "dev 1, calib 1, heldout 1", "?", "-"]
    assert rows["dj-2026-10"] == ["dj-2026-10", "?", "?", "?", "?", "-"]
    assert rows["smoke"][-1] == "no" and rows["volunteers-2026-10"][-1] == "no"
    assert f"error: {root}/corpora/aishell3/manifest.jsonl:1: invalid JSON" in err
    assert f"error: {root}/corpora/dj-2026-10/corpus.toml: invalid TOML" in err


def test_a_directory_without_corpus_toml_is_a_broken_corpus_not_a_missing_one(root, capsys):
    (root / "corpora" / "half-made").mkdir()
    code, out, err = run(capsys, "--data", str(root), "corpora")
    assert code == 1 and "half-made" in out
    assert f"error: {root}/corpora/half-made/corpus.toml: no corpus.toml" in err


def test_the_data_option_is_in_the_help_of_the_tool_and_of_the_command(capsys):
    for argv in (["--help"], ["corpora", "--help"]):
        with pytest.raises(SystemExit) as stop:
            cli.main(argv)
        assert stop.value.code == 0
        assert "--data DIR" in capsys.readouterr().out


def test_the_data_option_may_follow_the_command_and_then_wins(root, tmp_path_factory, capsys):
    other = tmp_path_factory.mktemp("other")
    code, out, _ = run(capsys, "corpora", "--data", str(root))
    assert code == 0 and f"data root: {root}" in out
    _, out, _ = run(capsys, "--data", str(other), "corpora", "--data", str(root))
    assert f"data root: {root}" in out


@pytest.mark.parametrize("argv", [["--data", "", "corpora"], ["corpora", "--data", " "]])
def test_an_empty_data_option_is_refused_not_the_current_directory(tmp_path, monkeypatch, capsys, argv):
    monkeypatch.chdir(tmp_path)
    code, out, err = run(capsys, *argv)
    assert code == 1 and out == ""
    assert err == "error: --data is empty; give a directory, or leave it out for $TONEKIT_DATA\n"


def test_a_symlinked_corpus_is_listed_and_one_whose_disk_is_gone_is_an_error(root, tmp_path_factory, capsys):
    elsewhere = tmp_path_factory.mktemp("external")
    add_corpus(elsewhere, "aishell3-ext", kind="recorded", source="dj-corpus", speakers=[speaker("dj")],
               clips=speaker_clips("dj", "dj-corpus"))  # fmt: skip
    (root / "corpora" / "aishell3-ext").symlink_to(elsewhere / "corpora" / "aishell3-ext")
    (root / "corpora" / "unmounted").symlink_to(elsewhere / "no-such-disk")
    code, out, err = run(capsys, "--data", str(root), "corpora")
    rows = {r[0]: r for r in table(out)}
    assert rows["aishell3-ext"] == ["aishell3-ext", "recorded", "dj-corpus", "gate 1", "gate 2", "no"]
    assert code == 1 and rows["unmounted"][1:] == ["?", "?", "?", "?", "-"]
    assert f"corpora/unmounted: a symlink to {elsewhere / 'no-such-disk'}, which is not a directory" in err


def test_intakes_staging_areas_are_not_corpora(root, capsys):
    (root / "corpora" / ".intake-K7Q2MD-123").mkdir()
    code, out, _ = run(capsys, "--data", str(root), "corpora")
    assert code == 0 and ".intake" not in out


def test_a_pack_that_cannot_be_read_is_one_error_not_a_broken_row_per_corpus(root, tmp_path, capsys):
    code, out, err = run(capsys, "--data", str(root), "corpora", "--pack", str(tmp_path / "nope.toml"))
    assert code == 1 and out == "" and "nope.toml" in err
