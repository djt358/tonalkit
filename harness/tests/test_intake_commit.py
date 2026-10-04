"""Moving staged files into a corpus as one change: a failure undoes what was done."""

from __future__ import annotations

import pytest

from tonekit_harness.intake.commit import MoveNew, Replace, apply_all


def test_all_steps_done_in_order(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "a").write_text("new a", encoding="utf-8")
    (tmp_path / "s" / "m").write_text("new m", encoding="utf-8")
    (tmp_path / "m").write_text("old m", encoding="utf-8")
    apply_all([MoveNew(tmp_path / "s" / "a", tmp_path / "x" / "y" / "a"), Replace(tmp_path / "s" / "m", tmp_path / "m")])
    assert (tmp_path / "x" / "y" / "a").read_text() == "new a" and (tmp_path / "m").read_text() == "new m"


def test_a_failing_step_undoes_the_earlier_ones_and_removes_the_directories_they_made(tmp_path):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "a").write_text("new a", encoding="utf-8")
    (tmp_path / "s" / "m").write_text("new m", encoding="utf-8")
    (tmp_path / "m").write_text("old m", encoding="utf-8")
    (tmp_path / "s" / "n").write_text("new n", encoding="utf-8")
    steps = [
        MoveNew(tmp_path / "s" / "a", tmp_path / "x" / "y" / "a"),
        Replace(tmp_path / "s" / "m", tmp_path / "m"),
        Replace(tmp_path / "s" / "n", tmp_path / "fresh"),
        MoveNew(tmp_path / "s" / "missing", tmp_path / "z"),  # fails: no such source
    ]
    with pytest.raises(FileNotFoundError):
        apply_all(steps)
    assert (tmp_path / "m").read_text() == "old m"
    assert not (tmp_path / "x").exists() and not (tmp_path / "fresh").exists()
    assert sorted(p.name for p in (tmp_path / "s").iterdir()) == ["a"]


def test_moving_onto_something_that_exists_is_refused(tmp_path):
    (tmp_path / "a").write_text("1", encoding="utf-8")
    (tmp_path / "b").write_text("2", encoding="utf-8")
    with pytest.raises(FileExistsError):
        apply_all([MoveNew(tmp_path / "a", tmp_path / "b")])
    assert (tmp_path / "b").read_text() == "2"
