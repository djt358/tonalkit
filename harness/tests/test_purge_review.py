"""Purge and what listening left behind: the review pages that link a session's audio, its entries
in the corpus's relabel log, and a new manifest a killed relabel left (contracts.md section 6)."""

from __future__ import annotations

from datetime import UTC, datetime

from intake_support import tkh
from relabel_support import CODE, CORPUS, corpus_dir, decision, log_lines, make_corpus, relabel, results_file

from tonekit_harness.contracts.registry import load_purge_log
from tonekit_harness.intake import purge_cli
from tonekit_harness.intake.purge import purge_session
from tonekit_harness.repo import repo_root
from tonekit_harness.review.page import write_page
from tonekit_harness.review.view import ReviewOptions, page_data

OTHER = "ABCDEF"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


def purge(root, code, tmp_path):
    return purge_session(root, code, repo=repo_root(), cache_dir=tmp_path / "cache", now=NOW)


def review(root, corpus=CORPUS):
    write_page(root, corpus, page_data(ReviewOptions(root=root, corpus_id=corpus, repo=repo_root())))
    return root / "review" / corpus


def test_purge_removes_the_review_page_that_links_the_session_and_keeps_other_pages(tmp_path):
    root = make_corpus(tmp_path, (CODE, OTHER))
    page = review(root)
    unrelated = root / "review" / "another-corpus"
    unrelated.mkdir()
    (unrelated / "index.html").write_text("<p>nothing of that session</p>")
    outcome = purge(root, CODE, tmp_path)
    assert not page.exists() and unrelated.is_dir()
    assert outcome.review_pages == 1
    # 8 clips and the session.json copy, and the page
    assert load_purge_log(root / "purge-log.jsonl")[0].files_removed == 10


def test_a_review_page_alone_is_still_purged(tmp_path):
    root = make_corpus(tmp_path)
    page = review(root)
    purge(root, CODE, tmp_path)  # the session is gone, the page with it
    assert not page.exists()
    leftover = root / "review" / CORPUS
    leftover.mkdir(parents=True)
    (leftover / "index.html").write_text(f"a page from before, naming {CODE}-g01-c")
    outcome = purge(root, CODE, tmp_path)
    assert outcome is not None and outcome.review_pages == 1 and not leftover.exists()


def test_purge_removes_the_sessions_relabel_log_entries_and_keeps_the_others(tmp_path):
    root = make_corpus(tmp_path, (CODE, OTHER))
    relabel(root, decision(f"{CODE}-g01-e", "heard", ["4", "1", "3"]), decision(f"{OTHER}-g02-e", "exclude"))
    log = corpus_dir(root) / "relabels.jsonl"
    others = [line for line in log.read_text().splitlines() if OTHER in line]
    purge(root, CODE, tmp_path)
    assert log.read_text().splitlines() == others
    assert {e["session"] for e in log_lines(root)} == {OTHER}
    assert CODE not in log.read_text()


def test_purge_removes_a_new_manifest_a_killed_relabel_left_behind(tmp_path):
    root = make_corpus(tmp_path, (CODE, OTHER))
    stray = corpus_dir(root) / ".manifest.jsonl.relabel-4242"
    stray.write_text(f'{{"id": "{CODE}-g01-c"}}\n')
    purge(root, CODE, tmp_path)
    assert not stray.exists()


def test_tkh_purge_says_it_removed_the_review_page_and_reminds_of_exported_decisions(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(purge_cli, "DEFAULT_CACHE_DIR", tmp_path / "cache")  # never the checkout's cache
    root = make_corpus(tmp_path)
    review(root)
    code, out, err = tkh(capsys, "purge", "--session", CODE, "--data", str(root))
    assert code == 0, err
    assert "removed 1 review page(s) that linked its audio" in out
    assert "relabels-*.json you exported from a review page" in out


def test_purge_removes_the_eval_results_file_that_lists_the_session(tmp_path):
    root = make_corpus(tmp_path)
    results = results_file(root, {f"{CODE}-g01-c": ["4", "1", "3"]})
    purge(root, CODE, tmp_path)
    assert not results.exists()
