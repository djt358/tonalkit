"""Stale markers as purge writes them: `contracts.registry.StaleMarker` at stale/<corpus>.json."""

from __future__ import annotations

from datetime import UTC, datetime

from tonekit_harness.contracts.registry import StaleMarker, stale_path
from tonekit_harness.intake.stale import UNREADABLE, mark_stale

T1, T2 = datetime(2026, 10, 4, tzinfo=UTC), datetime(2026, 10, 5, tzinfo=UTC)


def marker(root) -> StaleMarker:
    return StaleMarker.model_validate_json(stale_path(root, "c").read_text(encoding="utf-8"))


def test_marking_writes_the_corpus_and_a_dated_reason(tmp_path):
    path = mark_stale(tmp_path, "c", "purged session ABCDEF", now=T1)
    assert path == tmp_path / "stale" / "c.json"
    assert marker(tmp_path).model_dump() == {"corpus": "c", "reasons": [{"reason": "purged session ABCDEF",
                                                                          "marked_at": T1}]}  # fmt: skip


def test_marking_twice_keeps_both_reasons_oldest_first(tmp_path):
    mark_stale(tmp_path, "c", "first", now=T1)
    mark_stale(tmp_path, "c", "second", now=T2)
    assert [(r.reason, r.marked_at) for r in marker(tmp_path).reasons] == [("first", T1), ("second", T2)]


def test_a_damaged_marker_is_replaced_and_the_new_one_says_so(tmp_path):
    stale_path(tmp_path, "c").parent.mkdir()
    stale_path(tmp_path, "c").write_text("{not json", encoding="utf-8")
    mark_stale(tmp_path, "c", "purged", now=T1)
    assert [r.reason for r in marker(tmp_path).reasons] == [UNREADABLE, "purged"]
