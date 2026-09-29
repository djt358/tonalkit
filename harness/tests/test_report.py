"""The markdown gate report and the `tkh eval` command."""

from __future__ import annotations

from pathlib import Path

import pytest
from support import gate_corpus, write_manifest

from tonekit_harness import cli, evaluate, metrics, report
from tonekit_harness.evaluate import Result, Syllable

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"


def res(cid, overall, *, set="gate", pair=None, label="correct", rank=1, syllables=None, **kw):
    return Result(
        id=cid,
        set=set,
        pair=pair,
        label=label,
        speaker="dj",
        overall=overall,
        intended_rank=rank,
        margin_llr=kw.get("margin_llr", 0.5),
        syllables=syllables or [],
        register_source=kw.get("register_source", "cold"),
        issues=kw.get("issues", []),
    )


def gate_results(scores):
    out = []
    for i, (c, w) in enumerate(scores, start=1):
        pair = f"gate-{i:02d}"
        out.append(res(f"{pair}-correct", c, pair=pair, label="correct"))
        out.append(res(f"{pair}-error", w, pair=pair, label="tone_error"))
    return out


SYLLABLES = [
    Syllable("4", "4", 0.91, 0.3, "Full", []),
    Syllable(
        "1", "2", 0.22, 1.7, "Partial",
        [("NarrowerRange", 0.4), ("StartHigher", 1.86), ("TurnLater", 45.0)],
    ),  # fmt: skip
    Syllable("3", None, 0.0, None, "NotMeasured", []),
]


def render(results, tmp_path, **kw) -> str:
    gate = metrics.loo_gate(results)
    theta = gate.median_threshold
    out = tmp_path / "gate.md"
    report.write(
        out,
        gate,
        metrics.candidate_id_accuracy(results),
        metrics.count_robustness(results, theta),
        metrics.failures(results, gate, theta),
        **kw,
    )
    return out.read_text(encoding="utf-8")


def passing_results():
    return gate_results([(0.6 + 0.01 * i, 0.1 + 0.01 * i) for i in range(20)])


def failing_results():
    scores = [(0.6 + 0.01 * i, 0.1 + 0.01 * i) for i in range(20)]
    scores[4] = (0.05, scores[4][1])
    results = gate_results(scores)
    for r in results:
        if r.id == "gate-05-correct":
            r.syllables = SYLLABLES
            r.issues = ["LowSnr"]
    return results


def test_a_passing_gate_says_pass_with_ca_and_wa(tmp_path):
    text = render(passing_results(), tmp_path)
    first = next(line for line in text.splitlines() if line.strip())
    assert first.startswith("# ")
    assert "**S1: PASS**" in text
    assert "correct-accept 1.000" in text and "wrong-accept 0.000" in text
    assert "20 gate pairs" in text
    assert "S1: FAIL" not in text


def test_a_failing_gate_says_fail_and_which_bound_broke(tmp_path):
    scores = [(0.6 + 0.01 * i, 0.1 + 0.01 * i) for i in range(20)]
    for i in (2, 4, 6):
        scores[i] = (0.05, scores[i][1])  # CA 0.85
    text = render(gate_results(scores), tmp_path)
    assert "**S1: FAIL**" in text
    assert "correct-accept 0.850" in text
    assert "S1: PASS" not in text
    # The metrics table marks the correct-accept row failed and the wrong-accept row passed.
    rows = {line.split("|")[1].strip(): line for line in text.splitlines() if line.startswith("| ")}
    assert "fail" in rows["Correct-accept (leave-one-pair-out)"]
    assert "pass" in rows["Wrong-accept (leave-one-pair-out)"]


def test_the_metrics_table_has_counts_diagnostics_and_the_median_threshold(tmp_path):
    results = passing_results() + [
        res("min-1", 0.5, set="diag_minimal", rank=1),
        res("min-2", 0.5, set="diag_minimal", rank=2),
        res("cnt-1", 0.9, set="diag_count", rank=1),
    ]
    text = render(results, tmp_path, n_minimal=2, n_count=1)
    assert "20/20" in text  # correct accepted / correct clips
    assert "0.500 (1/2)" in text  # candidate-ID accuracy
    assert "1.000 (1/1)" in text  # count robustness
    assert "Median threshold" in text


def test_diagnostics_without_clips_read_n_a(tmp_path):
    text = render(passing_results(), tmp_path)
    assert "n/a" in text


def test_the_per_pair_table_lists_every_held_out_pair(tmp_path):
    text = render(passing_results(), tmp_path)
    for i in range(1, 21):
        assert f"| gate-{i:02d} |" in text


def test_failures_show_clip_id_scores_per_syllable_p_and_top_deltas(tmp_path):
    text = render(failing_results(), tmp_path)
    assert "## Failures" in text
    assert "### gate-05-correct" in text
    section = text[text.index("### gate-05-correct") :]
    assert "correct clip rejected" in section
    assert "LowSnr" in section
    assert "0.050" in section  # overall
    # Per-syllable table: p_correct, distance, measured kind and the two largest deltas.
    assert "0.910" in section and "0.220" in section
    assert "StartHigher 1.86" in section
    assert "TurnLater 45 ms" in section
    assert "NarrowerRange" not in section  # only the top two deltas by size
    assert "NotMeasured" in section


def test_a_gate_with_no_failures_says_so(tmp_path):
    text = render(passing_results(), tmp_path)
    assert "## Failures" in text
    section = text[text.index("## Failures") :]
    assert "None" in section


def test_clips_with_no_score_are_listed_as_rejects(tmp_path):
    scores = [(0.6 + 0.01 * i, 0.1 + 0.01 * i) for i in range(5)]
    scores[2] = (None, 0.12)
    text = render(gate_results(scores), tmp_path)
    assert "gate-03-correct" in text[text.index("no score") :]
    assert "not measured" in text


def test_diag_failures_appear_after_gate_failures(tmp_path):
    results = failing_results() + [res("min-3", 0.5, set="diag_minimal", rank=3)]
    text = render(results, tmp_path)
    assert text.index("### gate-05-correct") < text.index("### min-3")
    assert "ranked 3" in text


def test_the_report_is_deterministic_whatever_the_result_order(tmp_path):
    results = failing_results()
    a = render(results, tmp_path)
    b = render(list(reversed(results)), tmp_path)
    assert a == b


def test_the_report_carries_run_context_when_given(tmp_path):
    text = render(passing_results(), tmp_path, context={"manifest": "corpus/manifest.jsonl"})
    assert "manifest: `corpus/manifest.jsonl`" in text


def test_write_creates_missing_directories(tmp_path):
    gate = metrics.loo_gate(passing_results())
    out = tmp_path / "reports" / "nested" / "p0-gate.md"
    report.write(out, gate, None, None, [])
    assert out.is_file()


# ---- tkh eval ---------------------------------------------------------------------------------


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    root = tmp_path / "corpus"
    write_manifest(root / "manifest.jsonl", gate_corpus(root))
    monkeypatch.setattr(evaluate, "DEFAULT_CACHE_DIR", tmp_path / "cache")
    return root


def eval_args(corpus: Path, tmp_path: Path, *extra: str) -> list[str]:
    return [
        "eval",
        "--manifest", str(corpus / "manifest.jsonl"),
        "--pack", str(PACKS / "cmn.toml"),
        "--calib", str(PACKS / "cmn.calib.json"),
        "--report", str(tmp_path / "reports" / "p0-gate.md"),
        *extra,
    ]  # fmt: skip


def test_tkh_eval_writes_the_report_and_exits_zero_whatever_the_gate_says(
    corpus, tmp_path, capsys
):
    code = cli.main(eval_args(corpus, tmp_path))
    assert code == 0
    text = (tmp_path / "reports" / "p0-gate.md").read_text(encoding="utf-8")
    assert "**S1: " in text
    out = capsys.readouterr().out
    assert "S1:" in out and "p0-gate.md" in out
    assert f"manifest: `{corpus / 'manifest.jsonl'}`" in text  # run context
    assert (tmp_path / "cache").is_dir()  # analyses were cached


def test_tkh_eval_no_cache_leaves_the_cache_alone(corpus, tmp_path):
    assert cli.main(eval_args(corpus, tmp_path, "--no-cache", "--accent", "cmn-standard")) == 0
    assert not (tmp_path / "cache").exists()


def test_tkh_eval_calib_is_optional(corpus, tmp_path):
    args = eval_args(corpus, tmp_path)
    i = args.index("--calib")
    assert cli.main(args[:i] + args[i + 2 :]) == 0


def test_tkh_eval_errors_exit_non_zero_with_a_message(corpus, tmp_path, capsys):
    args = eval_args(corpus, tmp_path)
    missing = ["--manifest", str(corpus / "nope.jsonl")]
    i = args.index("--manifest")
    assert cli.main(args[:i] + missing + args[i + 2 :]) == 1
    assert "error:" in capsys.readouterr().err

    assert cli.main(eval_args(corpus, tmp_path, "--accent", "cmn-nowhere")) == 1
    assert "accent" in capsys.readouterr().err
    assert not (tmp_path / "reports" / "p0-gate.md").exists()


def test_tkh_eval_with_fewer_than_two_gate_pairs_is_an_error(corpus, tmp_path, capsys):
    lines = (corpus / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    (corpus / "manifest.jsonl").write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    assert cli.main(eval_args(corpus, tmp_path)) == 1
    assert "at least 2 gate pairs" in capsys.readouterr().err


def test_clip_paths_are_relative_to_the_manifest_directory(
    corpus, tmp_path, monkeypatch
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # the clips are not below the working directory
    assert cli.main(eval_args(corpus, tmp_path)) == 0
