"""`tkh purge --session CODE`: what it says, and that it always ends with what only DJ can delete."""

from __future__ import annotations

import pytest
from intake_support import kit_bundle, tkh

from tonekit_harness.intake import purge_cli

REMINDER = "What only you can delete: the original zip"


@pytest.fixture(autouse=True)
def cache(tmp_path, monkeypatch):
    """Never the checkout's real analysis cache."""
    d = tmp_path / "cache"
    d.mkdir()
    (d / "entry.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(purge_cli, "DEFAULT_CACHE_DIR", d)
    return d


def test_purge_says_what_it_removed_and_ends_with_the_reminder(tmp_path, capsys, cache):
    data = tmp_path / "data"
    tkh(capsys, "intake", str(kit_bundle(tmp_path / "in")), "--data", str(data))
    code, out, err = tkh(capsys, "purge", "--session", "K7Q2MD", "--data", str(data))
    assert code == 0 and err == ""
    lines = out.strip().splitlines()
    assert lines[0] == "purge K7Q2MD"
    assert "corpus volunteers-s05-v1: removed speaker v-k7q2md, 6 manifest rows, audio, session.json copy" in out
    assert "marked stale" in out and f"cleared tkh eval's analysis cache (1 entries in {cache})" in out
    assert f"logged in {data / 'purge-log.jsonl'} (7 session files removed)" in out
    assert lines[-1].startswith(REMINDER)


def test_an_unknown_code_says_nothing_found_and_still_reminds(tmp_path, capsys):
    code, out, _ = tkh(capsys, "purge", "--session", "ABCDEF", "--data", str(tmp_path / "data"))
    assert code == 0
    assert out.startswith(f"purge ABCDEF: nothing found under {tmp_path / 'data'}; nothing changed")
    assert out.strip().splitlines()[-1].startswith(REMINDER)
    assert not (tmp_path / "data").exists()


def test_a_code_typed_in_lower_case_is_the_same_code(tmp_path, capsys):
    data = tmp_path / "data"
    tkh(capsys, "intake", str(kit_bundle(tmp_path / "in")), "--data", str(data))
    _, out, _ = tkh(capsys, "purge", "--session", " k7q2md ", "--data", str(data))
    assert out.startswith("purge K7Q2MD\n")


@pytest.mark.parametrize("bad", ["K7Q2M", "K7Q2MDX", "K0Q2MD", "K7-2MD"])
def test_something_that_is_not_a_code_is_refused(tmp_path, capsys, bad):
    code, out, err = tkh(capsys, "purge", "--session", bad, "--data", str(tmp_path / "data"))
    assert code == 1 and out == "" and "is not a session code" in err
