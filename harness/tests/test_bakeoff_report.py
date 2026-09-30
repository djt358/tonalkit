"""The bakeoff markdown, from hand-made results: the tables, and the observation lines, which say
what the numbers show and never decide anything."""

from __future__ import annotations

import pytest

from tonekit_harness import bakeoff_report, conditions, metrics
from tonekit_harness.bakeoff import Bakeoff, GateScores, Group
from tonekit_harness.clearance import Clearance
from tonekit_harness.evaluate import Result
from tonekit_harness.pitch_metrics import Counts


def result(cid: str, pair: str, label: str, overall: float | None) -> Result:
    return Result(
        id=cid, set="gate", pair=pair, label=label, speaker="dj", overall=overall,
        intended_rank=1, margin_llr=0.0, syllables=[], register_source="cold",
    )  # fmt: skip


def gate_scores(correct: list[float], wrong: list[float], n_minimal: int = 0) -> GateScores:
    rows = []
    for i, (c, w) in enumerate(zip(correct, wrong, strict=True), start=1):
        rows += [result(f"c{i}", f"p{i}", "correct", c), result(f"w{i}", f"p{i}", "tone_error", w)]
    return GateScores(metrics.loo_gate(rows), 0.75 if n_minimal else None, n_minimal)


GATE = Clearance("gate")
PASSING = gate_scores([0.9, 0.8, 0.85], [0.1, 0.2, 0.15])  # every pair separated
FAILING = gate_scores([0.5, 0.5, 0.5], [0.5, 0.5, 0.5])  # nothing separates them


REPAIRED = "swift-f0 (after tonekit's octave repair)"


def measured(pyin: Counts, swift: Counts, repaired: Counts) -> dict[str, Counts]:
    return {"pyin": pyin, "swift-f0": swift, REPAIRED: repaired}


def synthetic_result() -> Bakeoff:
    return Bakeoff(
        synthetic={
            "clean": Group(
                2,
                measured(Counts(100, 80, 8, 5), Counts(100, 90, 1, 2), Counts(100, 88, 1, 2)),
            ),
            "noise ~5 dB": Group(
                1,
                measured(Counts(50, 10, 1, 20), Counts(50, 20, 5, 30), Counts(50, 20, 2, 30)),
            ),
            "noise ~10 dB": Group(
                1,
                measured(Counts(50, 10, 5, 20), Counts(50, 20, 10, 30), Counts(50, 20, 10, 30)),
            ),
            "noise ~20 dB": Group(
                1,
                measured(Counts(10, 0, 0, 10), Counts(10, 0, 0, 10), Counts(10, 0, 0, 10)),
            ),
        },
        gate=None,
    )


def render(tmp_path, bakeoff: Bakeoff, context=None) -> str:
    out = tmp_path / "sub" / "report.md"
    bakeoff_report.write(out, bakeoff, context=context)
    return out.read_text(encoding="utf-8")


def test_the_synthetic_table_has_a_row_per_condition_and_provider(tmp_path):
    text = render(tmp_path, synthetic_result())
    assert text.startswith("# P0 f0 bakeoff: pYIN against SwiftF0\n")
    assert "| Condition | Clips | Provider | Frames | Voiced in both | GPE | VDE |" in text
    assert "| clean | 2 | pyin | 100 | 80 | 0.100 (8/80) | 0.050 (5/100) |" in text
    assert "| clean | 2 | swift-f0 | 100 | 90 | 0.011 (1/90) | 0.020 (2/100) |" in text
    assert f"| clean | 2 | {REPAIRED} | 100 | 88 | 0.011 (1/88) | 0.020 (2/100) |" in text
    assert "| noise ~20 dB | 1 | pyin | 10 | 0 | n/a | 1.000 (10/10) |" in text
    assert "## Gate S1" not in text  # no gate run: no gate section


def test_the_observation_names_the_lower_gpe_per_condition_with_ties_and_gaps(tmp_path):
    text = render(tmp_path, synthetic_result())
    # clean: 0.100, 0.0111, 0.0114; noise 5 dB: 0.100, 0.250, 0.100; noise 10 dB: 0.5 all three;
    # noise 20 dB: no frame voiced in both
    assert (
        f"Lower GPE, by condition: clean swift-f0; noise ~5 dB pyin and {REPAIRED}; "
        "noise ~10 dB tie; noise ~20 dB n/a." in text
    )


def test_the_observation_names_the_lower_vde_too(tmp_path):
    text = render(tmp_path, synthetic_result())
    # clean: 0.05, 0.02, 0.02; noise 5 dB: 0.4, 0.6, 0.6; noise 10 dB: 0.4, 0.6, 0.6; 20 dB: 1.0 all
    assert (
        f"Lower VDE, by condition: clean swift-f0 and {REPAIRED}; noise ~5 dB pyin; "
        "noise ~10 dB pyin; noise ~20 dB tie." in text
    )


def test_the_report_says_how_the_tracks_were_measured(tmp_path):
    text = render(tmp_path, synthetic_result())
    for phrase in ("octave repair", "10 ms grid", "20%", "pooled"):
        assert phrase in text
    assert "GPE is conditional on each provider's own voicing" in text
    assert "Voiced in both" in text.split("conditional on")[1]  # and says where to read the counts
    assert "below -35 dBFS is scaled up to a peak of 0.5 before SwiftF0 sees it" in text


def test_the_snr_buckets_in_the_text_come_from_the_bucket_constant(tmp_path, monkeypatch):
    assert "nearest of 5, 10 and 20 dB" in render(tmp_path, synthetic_result())
    monkeypatch.setattr(conditions, "NOISE_BUCKETS_DB", (3.0, 6.0))
    assert "nearest of 3 and 6 dB" in render(tmp_path, synthetic_result())


def test_the_gate_table_and_verdict(tmp_path):
    both = Bakeoff(synthetic=None, gate={"pyin": PASSING, "swift-f0": FAILING}, clearance=GATE)
    text = render(tmp_path, both)
    assert (
        "| Provider | Correct-accept | Wrong-accept | S1 | Median threshold "
        "| Candidate-ID accuracy |" in text
    )
    assert "S1 (leave-one-pair-out): pyin PASS, swift-f0 FAIL." in text
    assert "| pyin | 1.000 (3/3) | 0.000 (0/3) | PASS |" in text
    assert "| swift-f0 | 1.000 (3/3) | 1.000 (3/3) | FAIL |" in text
    assert "## Synthetic f0 accuracy" not in text


def test_candidate_id_accuracy_is_shown_when_there_are_diag_minimal_clips(tmp_path):
    with_minimal = gate_scores([0.9, 0.8, 0.85], [0.1, 0.2, 0.15], n_minimal=4)
    text = render(tmp_path, Bakeoff(synthetic=None, gate={"pyin": with_minimal}, clearance=GATE))
    assert "0.750 (3/4)" in text
    assert "n/a (no clips)" in render(
        tmp_path, Bakeoff(synthetic=None, gate={"pyin": PASSING}, clearance=GATE)
    )


def test_both_sections_and_the_run_context_appear_in_order(tmp_path):
    both = Bakeoff(synthetic_result().synthetic, {"pyin": PASSING, "swift-f0": FAILING}, GATE)
    text = render(tmp_path, both, context={"pack": "cmn.toml", "swift-f0": "0.3.0"})
    assert text.index("## Run") < text.index("## Synthetic f0 accuracy") < text.index("## Gate S1")
    assert "- pack: cmn.toml\n- swift-f0: 0.3.0\n" in text


def test_the_output_is_deterministic(tmp_path):
    assert render(tmp_path, synthetic_result()) == render(tmp_path, synthetic_result())


def test_a_gate_run_that_is_not_a_gate_says_so_and_issues_no_verdict(tmp_path):
    no_verdict = Bakeoff(
        synthetic=None,
        gate={"pyin": PASSING, "swift-f0": FAILING},
        clearance=Clearance("not a gate", 6),
    )
    text = render(tmp_path, no_verdict)
    gate = text.split("## Gate S1")[1]
    assert "NOT A GATE (6 synthetic / non-allowed clips)" in gate
    assert "PASS" not in gate and "FAIL" not in gate
    assert "| pyin | 1.000 (3/3) | 0.000 (0/3) | n/a |" in gate  # the numbers, without a verdict
    assert "| swift-f0 | 1.000 (3/3) | 1.000 (3/3) | n/a |" in gate
    assert "some clips are synthetic or come from a source the data register does not allow" in gate


def test_a_smoke_gate_run_says_smoke(tmp_path):
    smoke = Bakeoff(synthetic=None, gate={"pyin": PASSING}, clearance=Clearance("smoke", 6))
    gate = render(tmp_path, smoke).split("## Gate S1")[1]
    assert "SMOKE (synthetic)" in gate and "a smoke run that checks the plumbing" in gate
    assert "PASS" not in gate and "FAIL" not in gate


def test_a_gate_result_without_its_clearance_cannot_be_written(tmp_path):
    with pytest.raises(ValueError, match="clearance"):
        render(tmp_path, Bakeoff(synthetic=None, gate={"pyin": PASSING}))
