"""Stale markers: what purge writes and the next successful run clears."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from registry_support import build_composed_root

from tonekit_harness.contracts.registry import RegistryError
from tonekit_harness.registry import DataRoot

T0 = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)


@pytest.fixture
def data(tmp_path):
    return DataRoot(build_composed_root(tmp_path))


def test_nothing_is_stale_to_begin_with(data):
    assert not data.is_stale("volunteers-2026-10")
    assert data.stale_marker("volunteers-2026-10") is None
    assert data.stale_corpus_ids() == []


def test_marking_a_corpus_makes_it_stale_and_says_why(data):
    marker = data.mark_stale("volunteers-2026-10", "session purged", now=T0)
    assert data.is_stale("volunteers-2026-10")
    assert [(r.reason, r.marked_at) for r in marker.reasons] == [("session purged", T0)]
    assert data.stale_marker("volunteers-2026-10") == marker
    assert not data.is_stale("dj-2026-10")  # per corpus


def test_the_marker_is_a_json_file_under_the_data_root_not_in_the_corpus(data):
    data.mark_stale("aishell3", "calibration refitted", now=T0)
    path = data.path / "stale" / "aishell3.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "corpus": "aishell3",
        "reasons": [{"reason": "calibration refitted", "marked_at": "2026-10-05T09:00:00Z"}],
    }
    assert not any(p.name.startswith("stale") for p in (data.corpora_dir / "aishell3").iterdir())


def test_marking_again_keeps_every_reason_in_order(data):
    data.mark_stale("volunteers-2026-10", "first", now=T0)
    marker = data.mark_stale("volunteers-2026-10", "second", now=T0 + timedelta(hours=1))
    assert [r.reason for r in marker.reasons] == ["first", "second"]
    assert [r.reason for r in data.stale_marker("volunteers-2026-10").reasons] == ["first", "second"]


def test_the_time_defaults_to_now(data):
    before = datetime.now(UTC)
    marker = data.mark_stale("dj-2026-10", "x")
    assert before <= marker.reasons[0].marked_at <= datetime.now(UTC)


def test_clearing_removes_the_reasons_marked_before_the_run_began(data):
    data.mark_stale("dj-2026-10", "x", now=T0)
    assert data.clear_stale("dj-2026-10", marked_before=T0 + timedelta(seconds=1)) is None
    assert not data.is_stale("dj-2026-10")
    assert data.clear_stale("dj-2026-10", marked_before=T0) is None  # nothing left to clear
    assert [p.name for p in (data.path / "stale").iterdir()] == []


def test_a_reason_marked_while_the_run_was_going_survives_the_clear(data):
    # The race: a run starts at T0 + 1h, a purge marks the corpus at T0 + 2h, the run finishes and
    # clears. The purge's reason must stay: the run never saw the purged corpus.
    data.mark_stale("dj-2026-10", "relabelled 2 clips", now=T0)
    data.mark_stale("dj-2026-10", "purged session ABCDEF", now=T0 + timedelta(hours=2))
    left = data.clear_stale("dj-2026-10", marked_before=T0 + timedelta(hours=1))
    assert [r.reason for r in left.reasons] == ["purged session ABCDEF"]
    assert data.stale_marker("dj-2026-10") == left
    assert [p.name for p in (data.path / "stale").iterdir()] == ["dj-2026-10.json"]


def test_a_marker_written_during_the_clear_is_merged_not_lost(data, monkeypatch):
    from tonekit_harness.registry import stale

    data.mark_stale("dj-2026-10", "old", now=T0)
    data.mark_stale("dj-2026-10", "during the run", now=T0 + timedelta(hours=2))
    real_read = stale._read

    def read_then_purge(path):  # a purge lands between the clear's claim and its rewrite
        marker = real_read(path)
        if path.name.startswith("."):
            stale.mark(data.path, "dj-2026-10", "purged meanwhile", now=T0 + timedelta(hours=3))
        return marker

    monkeypatch.setattr(stale, "_read", read_then_purge)
    left = data.clear_stale("dj-2026-10", marked_before=T0 + timedelta(hours=1))
    assert [r.reason for r in left.reasons] == ["during the run", "purged meanwhile"]


def test_an_unreadable_marker_counts_as_marked_when_it_was_written(data):
    data.mark_stale("dj-2026-10", "x")
    (data.path / "stale" / "dj-2026-10.json").write_text("{oops", encoding="utf-8")
    long_ago = datetime(2000, 1, 1, tzinfo=UTC)
    left = data.clear_stale("dj-2026-10", marked_before=long_ago)  # a run that began before it was written
    assert [r.reason for r in left.reasons] == ["an earlier stale marker could not be read and was replaced"]
    assert data.clear_stale("dj-2026-10", marked_before=datetime.now(UTC) + timedelta(seconds=1)) is None


def test_clearing_one_corpus_leaves_the_others_stale(data):
    for corpus in ("dj-2026-10", "aishell3", "smoke"):
        data.mark_stale(corpus, "x", now=T0)
    data.clear_stale("aishell3", marked_before=T0 + timedelta(seconds=1))
    assert data.stale_corpus_ids() == ["dj-2026-10", "smoke"]


def test_purge_and_relabel_get_the_markers_path(data):
    from tonekit_harness.registry.stale import mark_stale

    path = mark_stale(data.path, "dj-2026-10", "purged session ABCDEF", now=T0)
    assert path == data.path / "stale" / "dj-2026-10.json"
    assert data.stale_marker("dj-2026-10").reasons[0].reason == "purged session ABCDEF"


def test_the_same_reason_marked_twice_at_once_is_kept_once(data):
    data.mark_stale("dj-2026-10", "x", now=T0)
    marker = data.mark_stale("dj-2026-10", "x", now=T0)
    assert len(marker.reasons) == 1


def test_a_stale_corpus_is_still_selected_and_loaded(data):
    data.mark_stale("volunteers-2026-10", "session purged")
    assert len(data.select(["volunteers-*"])) == 6  # staleness flags outputs, it does not hide data


def test_a_reason_is_required(data):
    for blank in ("", "   "):
        with pytest.raises(ValueError, match="needs a reason"):
            data.mark_stale("dj-2026-10", blank)
    assert not data.is_stale("dj-2026-10")


def test_a_mistyped_corpus_is_an_error_not_a_marker_for_nothing(data):
    with pytest.raises(RegistryError, match=r"volunteers-2026-11: no such corpus \(have: aishell3"):
        data.mark_stale("volunteers-2026-11", "x")
    assert not (data.path / "stale").exists()


@pytest.mark.parametrize("bad", ["..", "../corpora/dj-2026-10", "a/b", ""])
def test_a_marker_cannot_be_written_outside_the_stale_directory(data, bad):
    with pytest.raises(RegistryError, match="no such corpus"):
        data.mark_stale(bad, "x")
    assert sorted(p.name for p in data.path.iterdir()) == ["corpora"]


def test_an_unreadable_marker_is_an_error_never_not_stale(data):
    data.mark_stale("dj-2026-10", "x")
    path = data.path / "stale" / "dj-2026-10.json"
    for content, message in [
        ("{oops", r"dj-2026-10\.json: invalid JSON"),
        ('{"corpus": "dj-2026-10", "reasons": []}', r"dj-2026-10\.json: reasons"),
        ('{"corpus": "dj-2026-10", "reasons": [{"reason": "x"}]}', r"dj-2026-10\.json: .*marked_at"),
    ]:
        path.write_text(content, encoding="utf-8")
        with pytest.raises(RegistryError, match=message):
            data.is_stale("dj-2026-10")
    path.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(RegistryError, match=r"dj-2026-10\.json: cannot read the stale marker"):
        data.stale_marker("dj-2026-10")


def test_marking_still_works_when_the_last_marker_is_damaged(data):
    data.mark_stale("dj-2026-10", "first", now=T0)
    (data.path / "stale" / "dj-2026-10.json").write_text("{oops", encoding="utf-8")
    marker = data.mark_stale("dj-2026-10", "purge", now=T0 + timedelta(hours=1))
    assert [r.reason for r in marker.reasons] == [
        "an earlier stale marker could not be read and was replaced",
        "purge",
    ]
    assert data.is_stale("dj-2026-10")  # readable again


def test_no_temporary_file_is_left_behind(data):
    data.mark_stale("dj-2026-10", "x")
    data.mark_stale("dj-2026-10", "y")
    assert [p.name for p in (data.path / "stale").iterdir()] == ["dj-2026-10.json"]
