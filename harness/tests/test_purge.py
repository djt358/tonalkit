"""`purge_session`: removes exactly what intake wrote for a session, logs it, marks the corpus
stale, and changes nothing the second time."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime

import pytest
from intake_support import entries, kit_bundle, options, tree

from tonekit_harness.contracts.registry import StaleMarker, load_corpus_file, load_purge_log
from tonekit_harness.intake.errors import IntakeError
from tonekit_harness.intake.purge import purge_session
from tonekit_harness.intake.run import intake_bundle
from tonekit_harness.repo import repo_root

CORPUS = "corpora/volunteers-s05-v1"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


@pytest.fixture
def root(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def cache(tmp_path):
    d = tmp_path / "cache"
    d.mkdir()
    for name in ("a.json", "b.json", "c.json.123.tmp"):
        (d / name).write_text("{}", encoding="utf-8")
    return d


def purge(root, code, cache_dir, now=NOW):
    return purge_session(root, code, repo=repo_root(), cache_dir=cache_dir, now=now)


def bookkeeping(files: dict[str, bytes]) -> dict[str, bytes]:
    """Everything but what purge adds: the log and the stale markers."""
    return {k: v for k, v in files.items() if k != "purge-log.jsonl" and not k.startswith("stale/")}


def test_purge_removes_exactly_what_intake_wrote(tmp_path, root, cache):
    intake_bundle(kit_bundle(tmp_path / "in", "ABCDEF"), options(root))
    before, listing = tree(root), entries(root)
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    outcome = purge(root, "K7Q2MD", cache)
    assert outcome is not None
    assert bookkeeping(tree(root)) == before
    assert [e for e in entries(root) if not e.startswith("stale") and e != "purge-log.jsonl"] == listing


def test_purging_the_only_session_leaves_the_corpus_without_speaker_rows_or_audio(tmp_path, root, cache):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    purge(root, "K7Q2MD", cache)
    assert sorted(bookkeeping(tree(root))) == [f"{CORPUS}/corpus.toml", f"{CORPUS}/manifest.jsonl"]
    assert (root / CORPUS / "manifest.jsonl").read_text() == ""
    assert load_corpus_file(root / CORPUS / "corpus.toml").speaker == []
    assert not (root / CORPUS / "audio").exists() and not (root / CORPUS / "sessions").exists()


def test_purge_logs_a_count_of_files_and_the_corpora_never_names(tmp_path, root, cache):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    purge(root, "K7Q2MD", cache)
    [record] = load_purge_log(root / "purge-log.jsonl")
    # six clips and the session.json copy; the cache is reported separately
    assert record.model_dump() == {"session": "K7Q2MD", "purged_at": NOW, "files_removed": 7,
                                   "corpora": ["volunteers-s05-v1"]}  # fmt: skip
    assert "g01" not in (root / "purge-log.jsonl").read_text()


def test_purge_marks_the_corpus_stale_and_keeps_earlier_reasons(tmp_path, root, cache):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    intake_bundle(kit_bundle(tmp_path / "in", "ABCDEF"), options(root))
    purge(root, "K7Q2MD", cache)
    purge(root, "ABCDEF", cache, now=datetime(2026, 10, 5, tzinfo=UTC))
    marker = StaleMarker.model_validate_json((root / "stale" / "volunteers-s05-v1.json").read_text())
    assert marker.corpus == "volunteers-s05-v1"
    assert [r.reason for r in marker.reasons] == ["purged session K7Q2MD", "purged session ABCDEF"]


def test_purge_clears_the_analysis_cache(tmp_path, root, cache):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    assert purge(root, "K7Q2MD", cache).cache_entries == 3
    assert list(cache.iterdir()) == []


def test_a_second_purge_finds_nothing_and_changes_nothing(tmp_path, root, cache):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    purge(root, "K7Q2MD", cache)
    (cache / "new.json").write_text("{}", encoding="utf-8")
    before = tree(root)
    assert purge(root, "K7Q2MD", cache) is None
    assert tree(root) == before and (cache / "new.json").exists()


def test_an_unknown_code_finds_nothing_in_an_empty_data_root(tmp_path, cache):
    assert purge(tmp_path / "none", "ABCDEF", cache) is None
    assert not (tmp_path / "none").exists()


def test_bundles_in_the_inbox_go_by_name_or_by_their_session_json(tmp_path, root, cache):
    inbox = root / "inbox"
    named = kit_bundle(inbox)  # tonekit-s05-v1-K7Q2MD.zip
    shutil.copy(named, inbox / "tonekit-s05-v1-K7Q2MD (1).zip")
    shutil.copy(named, inbox / "from-airdrop.zip")
    kit_bundle(inbox / "unzipped", folder=True).rename(inbox / "renamed-folder")
    other = kit_bundle(inbox, "ABCDEF")
    outcome = purge(root, "K7Q2MD", cache)
    assert outcome is not None and outcome.inbox == 4 and outcome.cache_entries == 0
    assert sorted(p.name for p in inbox.iterdir()) == sorted([other.name, "unzipped"])
    assert outcome.record.corpora == []


def test_a_staging_area_left_by_a_killed_intake_is_removed(root, cache):
    leftover = root / "corpora" / ".intake-K7Q2MD-77" / "audio" / "K7Q2MD"
    leftover.mkdir(parents=True)
    (leftover / "g01-c.wav").write_bytes(b"x")
    outcome = purge(root, "K7Q2MD", cache)
    assert outcome is not None and outcome.staging == 1 and outcome.record.files_removed == 1
    assert list((root / "corpora").iterdir()) == []


def test_a_speaker_with_other_sessions_keeps_them(tmp_path, root, cache):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    path = root / CORPUS / "corpus.toml"
    text = path.read_text().replace('id = "v-k7q2md"', 'id = "dj"').replace('["K7Q2MD"]', '["K7Q2MD", "ABCDEF"]')
    path.write_text(text, encoding="utf-8")
    purge(root, "K7Q2MD", cache)
    [speaker] = load_corpus_file(path).speaker
    assert (speaker.id, speaker.sessions) == ("dj", ["ABCDEF"])


def test_rows_purge_does_not_own_stay_byte_for_byte(tmp_path, root, cache):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    manifest = root / CORPUS / "manifest.jsonl"
    foreign = json.dumps({"id": "dj-1", "path": "dj/1.wav", "note": "not a valid row, and not ours"})
    manifest.write_text(foreign + "\n" + manifest.read_text() + "garbage line\n", encoding="utf-8")
    purge(root, "K7Q2MD", cache)
    assert manifest.read_text() == foreign + "\n" + "garbage line\n"


def test_an_unreadable_corpus_file_stops_purge_before_anything_is_removed(tmp_path, root, cache):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    (root / CORPUS / "corpus.toml").write_text("[corpus\nbroken", encoding="utf-8")
    before = tree(root)
    with pytest.raises(IntakeError, match="cannot read the corpus file"):
        purge(root, "K7Q2MD", cache)
    assert tree(root) == before and len(list(cache.iterdir())) == 3


def test_rows_of_a_manifest_in_a_subdirectory_are_found_by_their_audio(tmp_path, root, cache):
    corpus = root / "corpora" / "nested"
    corpus.mkdir(parents=True)
    (corpus / "corpus.toml").write_text(
        '[corpus]\nid = "nested"\nsource = "volunteer-corpus"\nkind = "recorded"\nlect = "cmn"\n'
        'manifest = "lists/manifest.jsonl"\n',
        encoding="utf-8",
    )
    intake_bundle(kit_bundle(tmp_path / "in"), options(root, corpus_id="nested"))
    lines = (corpus / "lists" / "manifest.jsonl").read_text().splitlines()
    renamed = [json.dumps(json.loads(line) | {"id": f"renamed-{i}"}) for i, line in enumerate(lines)]
    (corpus / "lists" / "manifest.jsonl").write_text("\n".join(renamed) + "\n", encoding="utf-8")
    outcome = purge(root, "K7Q2MD", cache)
    assert outcome is not None and outcome.corpora[0].rows == 6
    assert (corpus / "lists" / "manifest.jsonl").read_text() == ""
