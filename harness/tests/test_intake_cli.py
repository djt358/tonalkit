"""`tkh intake`: what it prints, the `tkh eval` command it suggests, and its exit codes."""

from __future__ import annotations

import shlex

from intake_support import kit_bundle, tkh

from tonekit_harness.repo import repo_root


def test_it_prints_speaker_clips_per_set_skipped_kept_out_and_corpus_path(tmp_path, capsys):
    bundle = kit_bundle(tmp_path / "in", cards=["r01", "g01-c", "g01-e", "g02-c", "m01-a"], skipped=["g02-e"])
    code, out, err = tkh(capsys, "intake", str(bundle), "--data", str(tmp_path / "data"))
    assert code == 0 and err == ""
    corpus = tmp_path / "data" / "corpora" / "volunteers-s05-v1"
    assert f"intake K7Q2MD ({bundle})" in out
    assert "deck: kit/deck/s05-v1.json" in out
    assert f"corpus: volunteers-s05-v1 (new) at {corpus}" in out
    assert "speaker: v-k7q2md, split gate" in out
    assert "clips kept: 4 (register 1, gate 2, diag_minimal 1)" in out
    assert "skipped by the speaker: 1 (g02-e)" in out
    assert "g02-c: its gate twin g02-e was not recorded" in out


def test_it_ends_with_the_eval_command_writing_the_report_under_the_data_root(tmp_path, capsys):
    data = tmp_path / "data"
    _, out, _ = tkh(capsys, "intake", str(kit_bundle(tmp_path / "in")), "--data", str(data))
    command = shlex.split(out.strip().splitlines()[-1])
    assert command[:4] == ["uv", "run", "tkh", "eval"]
    flags = dict(zip(command[4::2], command[5::2], strict=True))
    assert flags == {
        "--manifest": str(data / "corpora" / "volunteers-s05-v1" / "manifest.jsonl"),
        "--pack": str(repo_root() / "packs" / "cmn" / "cmn.toml"),
        "--report": str(data / "reports" / "volunteers-s05-v1.md"),
    }


def test_a_taiwan_speaker_gets_a_note_about_the_accent_tkh_eval_grades_against(tmp_path, capsys):
    _, out, _ = tkh(capsys, "intake", str(kit_bundle(tmp_path / "in")), "--data", str(tmp_path / "data"))
    assert "v-k7q2md's default accent is cmn-TW" in out and "--accent cmn-TW" in out


def test_several_bundles_one_refused_exit_1_and_the_rest_taken_in(tmp_path, capsys):
    good = kit_bundle(tmp_path / "a", "ABCDEF")
    missing = tmp_path / "nope.zip"
    code, out, err = tkh(capsys, "intake", str(missing), str(good), "--data", str(tmp_path / "data"))
    assert code == 1
    assert f"error: {missing}: " in err and "does not exist" in err
    assert "intake ABCDEF" in out and "uv run tkh eval" in out


def test_taking_the_same_bundle_twice_says_purge_first(tmp_path, capsys):
    bundle = kit_bundle(tmp_path / "in")
    tkh(capsys, "intake", str(bundle), "--data", str(tmp_path / "data"))
    code, out, err = tkh(capsys, "intake", str(bundle), "--data", str(tmp_path / "data"))
    assert code == 1 and out == ""
    assert "already in corpus volunteers-s05-v1" in err and "tkh purge --session K7Q2MD" in err


def test_the_data_root_defaults_to_tonekit_data(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("TONEKIT_DATA", str(tmp_path / "env-data"))
    code, _, _ = tkh(capsys, "intake", str(kit_bundle(tmp_path / "in")))
    assert code == 0 and (tmp_path / "env-data" / "corpora" / "volunteers-s05-v1" / "corpus.toml").is_file()


def test_an_empty_data_option_is_refused(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, _, err = tkh(capsys, "intake", str(kit_bundle(tmp_path / "in")), "--data", "")
    assert code == 1 and "--data is empty" in err
    assert not (tmp_path / "corpora").exists()
