"""atomic.write_text_atomic: the whole file or the old one, never half."""

from __future__ import annotations

from tonekit_harness.atomic import write_text_atomic


def test_it_writes_utf8_and_creates_the_parent_directories(tmp_path):
    path = tmp_path / "a" / "b" / "f.json"
    write_text_atomic(path, '{"字": 1}\n')
    assert path.read_text(encoding="utf-8") == '{"字": 1}\n'


def test_it_replaces_an_existing_file_and_leaves_no_temporary_file(tmp_path):
    path = tmp_path / "f.txt"
    path.write_text("old", encoding="utf-8")
    write_text_atomic(path, "new")
    assert path.read_text(encoding="utf-8") == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["f.txt"]
