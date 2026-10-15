"""`tkh relabel FILE --corpus ID [--data DIR]`: what it prints and its exit codes."""

from __future__ import annotations

import shlex

from intake_support import tkh, tree
from relabel_support import CODE, CORPUS, decision, export_file, make_corpus

G1E = f"{CODE}-g01-e"


def test_it_lists_each_row_it_changed_and_what_to_run_next(tmp_path, capsys):
    root = make_corpus(tmp_path)
    path = export_file(tmp_path, decision(G1E, "heard", ["4", "1", "3"]), decision(f"{CODE}-r01", "exclude"))
    code, out, err = tkh(capsys, "relabel", str(path), "--corpus", CORPUS, "--data", str(root))
    assert code == 0, err
    assert f"relabel {CORPUS} from {path.name} (2 decisions by DJ)" in out
    assert f"{G1E}: tone_error 4 1 4 -> correct 4 1 3; leaves pair {CODE}-g01" in out
    assert f"{CODE}-g01-c: leaves pair {CODE}-g01" in out
    assert f"{CODE}-r01: excluded (its audio stays until purge)" in out
    assert f"pairs left out of the gate (no longer one correct and one error reading; the clips stay for fitting): {CODE}-g01" in out
    assert "marked stale" in out
    *_, eval_line, review_line = out.strip().splitlines()
    assert shlex.split(eval_line)[2:4] == ["tkh", "eval"] and "--results" in eval_line
    assert shlex.split(review_line) == ["uv", "run", "tkh", "review", "--corpus", CORPUS, "--data", str(root)]


def test_the_second_run_says_there_is_nothing_to_change(tmp_path, capsys):
    root = make_corpus(tmp_path)
    path = export_file(tmp_path, decision(G1E, "unclear"))
    tkh(capsys, "relabel", str(path), "--corpus", CORPUS, "--data", str(root))
    code, out, _ = tkh(capsys, "relabel", str(path), "--corpus", CORPUS, "--data", str(root))
    assert code == 0 and "nothing to change" in out and "tkh eval" not in out


def test_a_file_that_is_not_an_export_or_for_another_corpus_exits_1_and_writes_nothing(tmp_path, capsys):
    root = make_corpus(tmp_path)
    files = tree(root)
    junk = tmp_path / "junk.json"
    junk.write_text("{}")
    code, _, err = tkh(capsys, "relabel", str(junk), "--corpus", CORPUS, "--data", str(root))
    assert code == 1 and "not a tonekit.relabels.v1 file" in err
    other = export_file(tmp_path, decision(G1E, "exclude"), corpus="other")
    code, _, err = tkh(capsys, "relabel", str(other), "--corpus", CORPUS, "--data", str(root))
    assert code == 1 and "for corpus 'other'" in err
    assert tree(root) == files
