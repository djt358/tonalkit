"""The markdown gate report and the `tkh eval` command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support import gate_corpus, write_manifest

from tonekit_harness import cli, evaluate, metrics, report
from tonekit_harness.clearance import Clearance
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
    # tonekit's order (by z-score), which is neither by amount nor alphabetical
    Syllable("1", "2", 0.22, 1.7, "Partial", [("WiderRange", 0.4), ("TurnLater", 45.0)]),
    Syllable("3", None, 0.0, None, "NotMeasured", []),
]


def render(results, tmp_path, **kw) -> str:
    gate = metrics.loo_gate(results)
    theta = gate.median_threshold
    out = tmp_path / "gate.md"
    kw.setdefault("clearance", Clearance("gate"))
    kw.setdefault("results", results)
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


def bound_results(wrong_accepted: int):
    """20 gate pairs: 2 correct clips rejected (CA 18/20) and `wrong_accepted` wrong clips accepted
    (2 sits exactly on the WA bound of 2/20, 3 is one over)."""
    scores = [(0.6 + 0.01 * i, 0.1 + 0.01 * i) for i in range(20)]
    for i in (2, 4):  # correct clips below every wrong clip: rejected
        scores[i] = (0.05, scores[i][1])
    for i, wrong in list(zip((6, 10, 14), (0.95, 0.96, 0.97)))[:wrong_accepted]:
        scores[i] = (scores[i][0], wrong)  # wrong clips above every correct clip: accepted
    return gate_results(scores)


def result_cells(text: str) -> dict[str, str]:
    """Metric name to its Result cell (the last column of the metrics table)."""
    rows = [line for line in text.splitlines() if line.startswith("| ")]
    return {cells[0]: cells[-1] for cells in ([c.strip() for c in line.strip("| ").split(" | ")] for line in rows)}


def test_a_gate_exactly_on_both_bounds_passes_and_the_report_agrees(tmp_path):
    """CA 18/20 and WA 2/20 are exactly the bounds. The float 0.1 is above Fraction(1, 10), so a
    float comparison would print the PASS headline next to "wrong-accept is above its bound"."""
    results = bound_results(wrong_accepted=2)
    assert metrics.loo_gate(results).passed is True
    text = render(results, tmp_path)
    assert "**S1: PASS**" in text and "S1: FAIL" not in text
    assert "correct-accept 0.900" in text and "wrong-accept 0.100" in text
    assert "above its bound" not in text and "below its bound" not in text
    cells = result_cells(text)
    assert cells["Correct-accept (leave-one-pair-out)"] == "pass"
    assert cells["Wrong-accept (leave-one-pair-out)"] == "pass"
    assert "0.900 (18/20)" in text and "0.100 (2/20)" in text


def test_a_gate_just_outside_a_bound_fails_and_names_that_bound(tmp_path):
    results = bound_results(wrong_accepted=3)  # WA 3/20 = 0.15
    text = render(results, tmp_path)
    assert "**S1: FAIL**" in text and "S1: PASS" not in text
    assert "Wrong-accept is above its bound." in text
    assert "below its bound" not in text
    cells = result_cells(text)
    assert cells["Wrong-accept (leave-one-pair-out)"] == "fail"
    assert cells["Correct-accept (leave-one-pair-out)"] == "pass"


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


def test_failures_show_clip_id_scores_per_syllable_p_and_deltas(tmp_path):
    text = render(failing_results(), tmp_path)
    assert "## Failures" in text
    assert "### gate-05-correct" in text
    section = text[text.index("### gate-05-correct") :]
    assert "correct clip rejected" in section
    assert "LowSnr" in section
    assert "0.050" in section  # overall
    # Per-syllable table: p_correct, distance, measured kind and the deltas, in the order
    # tonekit returned them (not re-sorted by amount, which would put 45 ms before 0.40 Chao).
    assert "0.910" in section and "0.220" in section
    assert "WiderRange 0.40, TurnLater 45 ms" in section
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
    assert "- manifest: corpus/manifest.jsonl" in text


def test_write_creates_missing_directories(tmp_path):
    gate = metrics.loo_gate(passing_results())
    out = tmp_path / "reports" / "nested" / "p0-gate.md"
    report.write(out, gate, None, None, [], clearance=Clearance("gate"))
    assert out.is_file()


def test_a_report_cannot_be_written_without_saying_whether_it_is_a_verdict(tmp_path):
    gate = metrics.loo_gate(passing_results())
    with pytest.raises(TypeError, match="clearance"):
        report.write(tmp_path / "gate.md", gate, None, None, [])  # type: ignore[call-arg]


# ---- no verdict for synthetic or non-allowed clips ---------------------------------------------


def test_a_run_that_is_not_a_gate_says_so_instead_of_pass(tmp_path):
    text = render(passing_results(), tmp_path, clearance=Clearance("not a gate", 3))
    first = next(line for line in text.splitlines() if line.startswith("**"))
    assert first.startswith("**NOT A GATE (3 synthetic / non-allowed clips)**")
    assert "S1: PASS" not in text and "S1: FAIL" not in text
    assert "not a gate verdict" in first
    # the numbers are still reported, as numbers
    assert "correct-accept 1.000" in first and "wrong-accept 0.000" in first and "20 gate pairs" in first


def test_a_smoke_run_says_smoke_instead_of_pass(tmp_path):
    text = render(failing_results(), tmp_path, clearance=Clearance("smoke", 40))
    first = next(line for line in text.splitlines() if line.startswith("**"))
    assert first.startswith("**SMOKE (synthetic)**")
    assert "S1: PASS" not in text and "S1: FAIL" not in text
    assert "plumbing" in first and "not a gate verdict" in first


@pytest.mark.parametrize("mode", [Clearance("not a gate", 1), Clearance("smoke", 1)])
def test_without_a_verdict_the_metrics_table_does_not_mark_rows_pass_or_fail(tmp_path, mode):
    results = bound_results(wrong_accepted=3)  # a real FAIL
    text = render(results, tmp_path, clearance=mode)
    cells = result_cells(text)
    assert cells["Correct-accept (leave-one-pair-out)"] == "n/a"
    assert cells["Wrong-accept (leave-one-pair-out)"] == "n/a"
    assert "above its bound" not in text and "below its bound" not in text
    assert "0.150 (3/20)" in text  # the wrong-accept number itself stays


def test_the_failures_are_still_listed_without_a_verdict(tmp_path):
    text = render(failing_results(), tmp_path, clearance=Clearance("smoke", 1))
    assert "### gate-05-correct" in text and "correct clip rejected" in text


# ---- tkh eval ---------------------------------------------------------------------------------


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    """The support gate corpus: synthetic audio, registered as `synthetic-world`."""
    root = tmp_path / "corpus"
    write_manifest(root / "manifest.jsonl", gate_corpus(root))
    monkeypatch.setattr(evaluate, "DEFAULT_CACHE_DIR", tmp_path / "cache")
    return root


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    """The same clips labelled as DJ's recordings (`dj-corpus`, allowed): only to exercise the
    PASS/FAIL headline, which a corpus of real recordings earns."""
    root = tmp_path / "recorded"
    write_manifest(root / "manifest.jsonl", gate_corpus(root, source="dj-corpus"))
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


def test_tkh_eval_writes_the_report_and_exits_zero_whatever_the_gate_says(recorded, tmp_path, capsys):
    code = cli.main(eval_args(recorded, tmp_path))
    assert code == 0
    text = (tmp_path / "reports" / "p0-gate.md").read_text(encoding="utf-8")
    assert "**S1: PASS**" in text or "**S1: FAIL**" in text
    assert "NOT A GATE" not in text and "SMOKE" not in text
    out = capsys.readouterr().out
    assert out.startswith(("S1: PASS", "S1: FAIL")) and "p0-gate.md" in out
    assert f"- manifest: {recorded / 'manifest.jsonl'}" in text  # run context
    assert (tmp_path / "cache").is_dir()  # analyses were cached


def test_tkh_eval_on_synthetic_clips_is_not_a_gate_and_still_exits_zero(corpus, tmp_path, capsys):
    assert cli.main(eval_args(corpus, tmp_path)) == 0
    text = (tmp_path / "reports" / "p0-gate.md").read_text(encoding="utf-8")
    assert "**NOT A GATE (4 synthetic / non-allowed clips)**" in text
    assert "S1: PASS" not in text and "S1: FAIL" not in text
    out = capsys.readouterr().out
    assert out.startswith("S1: NOT A GATE (4 synthetic / non-allowed clips)")
    assert "PASS" not in out and "FAIL" not in out


def test_tkh_eval_allow_synthetic_is_a_smoke_run(corpus, tmp_path, capsys):
    assert cli.main(eval_args(corpus, tmp_path, "--allow-synthetic")) == 0
    text = (tmp_path / "reports" / "p0-gate.md").read_text(encoding="utf-8")
    assert "**SMOKE (synthetic)**" in text
    assert "NOT A GATE" not in text and "S1: PASS" not in text and "S1: FAIL" not in text
    assert capsys.readouterr().out.startswith("S1: SMOKE (synthetic)")


def test_allow_synthetic_does_not_turn_a_real_corpus_into_a_smoke_run(recorded, tmp_path, capsys):
    assert cli.main(eval_args(recorded, tmp_path, "--allow-synthetic")) == 0
    assert capsys.readouterr().out.startswith(("S1: PASS", "S1: FAIL"))


def write_register(path: Path, rows: dict[str, str]) -> Path:
    body = "".join(f"{sid},{verdict}\n" for sid, verdict in rows.items())
    path.write_text("id,shipped_weights_training\n" + body, encoding="utf-8")
    return path


def test_tkh_eval_reads_clearance_from_the_register_it_is_given(recorded, tmp_path, capsys):
    register = write_register(tmp_path / "reg.csv", {"dj-corpus": "verify"})  # not yet signed off
    assert cli.main(eval_args(recorded, tmp_path, "--register", str(register))) == 0
    out = capsys.readouterr().out
    assert out.startswith("S1: NOT A GATE (4 synthetic / non-allowed clips)")
    text = (tmp_path / "reports" / "p0-gate.md").read_text(encoding="utf-8")
    assert f"- data register: {register}" in text


def test_a_source_that_is_not_a_register_id_is_an_error(recorded, tmp_path, capsys):
    register = write_register(tmp_path / "reg.csv", {"someone-else": "allow"})
    assert cli.main(eval_args(recorded, tmp_path, "--register", str(register))) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and "source 'dj-corpus' is not an id in the data register" in err
    assert not (tmp_path / "reports" / "p0-gate.md").exists()


def test_a_missing_or_unusable_register_is_an_error(recorded, tmp_path, capsys):
    nowhere = tmp_path / "nowhere.csv"
    assert cli.main(eval_args(recorded, tmp_path, "--register", str(nowhere))) == 1
    assert "nowhere.csv" in capsys.readouterr().err
    bad = tmp_path / "bad.csv"
    bad.write_text("id,license\ndj-corpus,owned\n", encoding="utf-8")
    assert cli.main(eval_args(recorded, tmp_path, "--register", str(bad))) == 1
    assert "missing column" in capsys.readouterr().err
    assert not (tmp_path / "reports" / "p0-gate.md").exists()


def test_a_manifest_mixing_synthetic_rows_into_the_gate_is_an_error(corpus, tmp_path, capsys):
    lines = (corpus / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    mixed = json.loads(lines[0])
    mixed.update(id="extra", set="synthetic", synthetic={"from": mixed["id"]})
    (corpus / "manifest.jsonl").write_text("\n".join([*lines, json.dumps(mixed)]) + "\n", encoding="utf-8")
    for extra in ([], ["--allow-synthetic"]):
        assert cli.main(eval_args(corpus, tmp_path, *extra)) == 1
        err = capsys.readouterr().err
        assert err.startswith("error: ") and "mixed with gate clips" in err
    assert not (tmp_path / "reports" / "p0-gate.md").exists()


def test_a_synthetic_field_on_a_gate_row_is_an_error_naming_the_line(corpus, tmp_path, capsys):
    lines = (corpus / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    first["synthetic"] = {"generator": "by hand"}
    lines[0] = json.dumps(first)
    (corpus / "manifest.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert cli.main(eval_args(corpus, tmp_path)) == 1
    err = capsys.readouterr().err
    assert ":1:" in err and "`synthetic` field" in err


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


def test_tkh_eval_an_unwritable_report_path_is_an_error(corpus, tmp_path, capsys):
    blocker = tmp_path / "reports"
    blocker.write_text("a file where the report directory should go", encoding="utf-8")
    assert cli.main(eval_args(corpus, tmp_path)) == 1
    assert "error:" in capsys.readouterr().err


def test_tkh_eval_with_fewer_than_two_gate_pairs_is_an_error(corpus, tmp_path, capsys):
    lines = (corpus / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    (corpus / "manifest.jsonl").write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")
    assert cli.main(eval_args(corpus, tmp_path)) == 1
    assert "at least 2 gate pairs" in capsys.readouterr().err


def test_clip_paths_are_relative_to_the_manifest_directory(corpus, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)  # the clips are not below the working directory
    assert cli.main(eval_args(corpus, tmp_path)) == 0


def fallback_pair(i, *, speaker="v-a", error_fallback=True, scored=False):
    """A gate pair whose error clip had a syllable with no nucleus: unscored (R104), or with
    `scored` its overall the fallback prior (results from before R104)."""
    pair = f"gate-{i:02d}"
    measured = Syllable("4", "4", 0.9, 0.4, "Full", [])
    missed = Syllable("3", None, 0.5, None, "NotMeasured", [], ["NoNucleus"])
    if scored:
        missed = Syllable("3", None, 0.047, None, "Partial", [], ["Unvoiced"])
    correct = res(f"{pair}-correct", 0.9, pair=pair, label="correct", syllables=[measured])
    error = res(
        f"{pair}-error",
        (0.047 if scored else None) if error_fallback else 0.001,
        pair=pair,
        label="tone_error",
        syllables=[measured, missed if error_fallback else Syllable("3", "2", 0.001, 3.0, "Full", [])],
    )
    correct.speaker = error.speaker = speaker
    return [correct, error]


def test_a_syllable_with_no_nucleus_leaves_its_clip_unscored(tmp_path):
    results = fallback_pair(1) + fallback_pair(2) + fallback_pair(3, error_fallback=False)
    text = render(results, tmp_path)
    table_text = "\n".join(report._failure(metrics.Failure(result=results[1], reason="x")))
    assert "no nucleus (fallback)" in table_text
    section = text.split("## Syllables with no nucleus\n", 1)[1].split("\n## ", 1)[0]
    assert "- v-a: 2 of 9 gate syllables had no nucleus; 2 of 6 clips rest on one" in section
    assert "- gate-01-error" in section and "- gate-02-error" in section and "gate-03-error" not in section
    assert "- gate-01-error" in text.split("## Clips with no score\n", 1)[1]


def test_results_from_before_r104_still_show_the_fallback(tmp_path):
    results = fallback_pair(1, scored=True) + fallback_pair(2, scored=True)
    assert results[1].decided_by_fallback and results[1].missing
    section = render(results, tmp_path).split("## Syllables with no nucleus\n", 1)[1]
    assert "- gate-01-error" in section and "- gate-02-error" in section


def test_an_unpitched_syllable_is_evidence_not_a_fallback(tmp_path):
    # R103: a creaky vowel is scored on the calibration's unpitched evidence: it has no distance,
    # but it is a measurement, and the report says which.
    results = fallback_pair(1, error_fallback=False) + fallback_pair(2, error_fallback=False)
    creaky = Syllable("3", "3", 0.7, None, "Partial", [], ["Unpitched"])
    results[1].syllables[1] = creaky
    assert not creaky.fallback and creaky.unpitched
    assert "Syllables with no nucleus" not in render(results, tmp_path)
    table_text = "\n".join(report._failure(metrics.Failure(result=results[1], reason="x")))
    assert "unpitched (creak evidence)" in table_text
    # The name a miss had before R102 still reads as one.
    assert Syllable("3", None, 0.047, None, "Partial", [], ["Unvoiced"]).fallback


def test_no_fallback_no_section(tmp_path):
    results = fallback_pair(1, error_fallback=False) + fallback_pair(2, error_fallback=False)
    assert "Syllables with no nucleus" not in render(results, tmp_path)


def test_tkh_eval_grades_only_the_speakers_asked_for(corpus, tmp_path, capsys):
    # A fit is scored on the speakers it was not fitted on (ruling R106).
    assert cli.main(eval_args(corpus, tmp_path, "--speaker", "dj")) == 0
    capsys.readouterr()
    assert cli.main(eval_args(corpus, tmp_path, "--speaker", "nobody")) == 1
    assert "no clips for speaker(s) nobody" in capsys.readouterr().err
