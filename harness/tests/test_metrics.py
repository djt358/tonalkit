"""Gate metrics on hand-built results: the leave-one-pair-out threshold, candidate-ID accuracy and
count robustness."""

from __future__ import annotations

import math

import pytest

from tonekit_harness import metrics
from tonekit_harness.evaluate import Result
from tonekit_harness.metrics import MetricsError


def res(
    cid: str,
    overall: float | None,
    *,
    set: str = "gate",
    pair: str | None = None,
    label: str = "correct",
    rank: int = 1,
) -> Result:
    return Result(
        id=cid,
        set=set,
        pair=pair,
        label=label,
        speaker="dj",
        overall=overall,
        intended_rank=rank,
        margin_llr=0.0,
        syllables=[],
        register_source="cold",
    )


def gate_pairs(scores: list[tuple[float | None, float | None]]) -> list[Result]:
    """One (correct, wrong) score pair per gate pair `gate-01`, `gate-02`, ..."""
    out: list[Result] = []
    for i, (correct, wrong) in enumerate(scores, start=1):
        pair = f"gate-{i:02d}"
        out.append(res(f"{pair}-correct", correct, pair=pair, label="correct"))
        out.append(res(f"{pair}-error", wrong, pair=pair, label="tone_error"))
    return out


# ---- loo_gate: the gate S1 ---------------------------------------------------------------


def test_perfectly_separated_scores_pass_with_ca_1_and_wa_0():
    results = gate_pairs([(0.60 + 0.01 * i, 0.10 + 0.01 * i) for i in range(20)])
    gate = metrics.loo_gate(results)
    assert gate.ca == 1.0
    assert gate.wa == 0.0
    assert gate.passed is True
    assert gate.rejected_none == []
    assert len(gate.thresholds) == 20
    # Every held-out threshold sits in the gap between the wrong and the correct scores.
    assert all(0.29 < theta < 0.60 for theta in gate.thresholds.values())
    assert list(gate.thresholds) == [f"gate-{i:02d}" for i in range(1, 21)]


def test_interleaved_scores_do_not_pass():
    # Within every pair the two scores are close, and which one is higher alternates, so no single
    # threshold separates correct from wrong.
    scores = []
    for i in range(20):
        base = 0.05 * i
        scores.append((base + 0.02, base) if i % 2 else (base, base + 0.02))
    gate = metrics.loo_gate(gate_pairs(scores))
    assert gate.passed is False
    assert not (gate.ca >= 0.90 and gate.wa <= 0.10)


def test_ca_0_90_and_wa_0_10_exactly_at_the_gate_edge_still_pass():
    """18/20 correct accepted and 2/20 wrong accepted is exactly CA 0.90, WA 0.10: still a pass."""
    scores = [(0.6 + 0.01 * i, 0.1 + 0.01 * i) for i in range(20)]
    for i in (2, 4):  # correct clips below every wrong clip: rejected
        scores[i] = (0.05, scores[i][1])
    for i, wrong in ((6, 0.95), (10, 0.96)):  # wrong clips above every correct clip: accepted
        scores[i] = (scores[i][0], wrong)
    gate = metrics.loo_gate(gate_pairs(scores))
    assert gate.ca == pytest.approx(0.90)
    assert gate.wa == pytest.approx(0.10)
    assert (gate.ca_ok, gate.wa_ok, gate.passed) == (True, True, True)

    scores[14] = (scores[14][0], 0.97)  # a third accepted wrong clip: WA 0.15
    over = metrics.loo_gate(gate_pairs(scores))
    assert over.wa == pytest.approx(0.15)
    assert (over.ca_ok, over.wa_ok, over.passed) == (True, False, False)

    scores[14] = (scores[14][0], 0.1 + 0.01 * 14)
    scores[16] = (0.05, scores[16][1])  # a third rejected correct clip: CA 0.85
    under = metrics.loo_gate(gate_pairs(scores))
    assert under.ca == pytest.approx(0.85)
    assert (under.ca_ok, under.wa_ok, under.passed) == (False, True, False)


def test_a_held_out_pair_is_judged_by_a_threshold_that_never_saw_it():
    """The other four pairs separate at 0.5; the held-out pair's correct clip scores 0.45, so it is
    rejected even though a threshold fitted with it (0.375) would have kept it."""
    results = gate_pairs([(0.8, 0.2), (0.9, 0.1), (0.45, 0.2), (0.7, 0.3), (0.85, 0.15)])
    gate = metrics.loo_gate(results)
    assert gate.accepted["gate-03-correct"] is False
    assert gate.accepted["gate-03-error"] is False
    assert gate.ca == pytest.approx(4 / 5)
    assert gate.wa == 0.0
    assert gate.passed is False


def test_a_none_score_is_a_reject_and_is_listed():
    scores = [(0.6 + 0.01 * i, 0.1 + 0.01 * i) for i in range(5)]
    scores[2] = (None, 0.12)
    gate = metrics.loo_gate(gate_pairs(scores))
    assert gate.rejected_none == ["gate-03-correct"]
    assert gate.ca == pytest.approx(4 / 5)
    assert gate.wa == 0.0
    assert gate.passed is False


def test_a_none_wrong_clip_is_a_reject_too_and_is_never_accepted_at_any_threshold():
    scores = [(0.6 + 0.01 * i, 0.1 + 0.01 * i) for i in range(5)]
    scores[1] = (0.61, None)
    gate = metrics.loo_gate(gate_pairs(scores))
    assert gate.rejected_none == ["gate-02-error"]
    assert gate.wa == 0.0
    assert gate.ca == 1.0
    assert gate.accepted["gate-02-error"] is False


@pytest.mark.parametrize(
    ("last_pair", "none_id", "measured_id"),
    [
        ((None, 0.7), "gate-03-correct", "gate-03-error"),
        ((0.3, None), "gate-03-error", "gate-03-correct"),
    ],
)
def test_a_none_score_is_a_reject_even_at_theta_minus_inf(last_pair, none_id, measured_id):
    """In the other pairs every wrong clip outscores every correct one, so the best J is 0 at -inf
    and +inf, tied, and the lower-middle is -inf. A literal -inf score would pass `-inf >= -inf`;
    keeping None as None makes the held-out clip a reject at any threshold."""
    gate = metrics.loo_gate(gate_pairs([(0.1, 0.9), (0.2, 0.8), last_pair]))
    assert gate.thresholds["gate-03"] == -math.inf
    assert gate.rejected_none == [none_id]
    assert gate.accepted[none_id] is False
    assert gate.accepted[measured_id] is True  # the same θ accepts the pair's measured clip


def test_none_scores_in_the_other_pairs_do_not_move_the_threshold():
    """Held-out gate-03's threshold is fitted on gate-01/02/04/05; the None there is skipped."""
    scores = [(0.6, 0.1), (None, 0.2), (0.7, 0.15), (0.8, 0.3), (0.9, None)]
    gate = metrics.loo_gate(gate_pairs(scores))
    theta = gate.thresholds["gate-03"]
    assert 0.3 < theta < 0.6  # between the highest wrong (0.3) and the lowest correct (0.6)
    assert gate.accepted["gate-03-correct"] is True
    assert gate.accepted["gate-03-error"] is False


def test_unmeasured_other_pairs_leave_theta_at_minus_inf_which_accepts_every_measured_score():
    scores = [(None, None), (None, None), (0.9, 0.1)]
    gate = metrics.loo_gate(gate_pairs(scores))
    # Held-out gate-03 saw only None scores: every candidate θ has J = 0; the tied set is
    # {-inf, +inf} and its lower-middle is -inf, which accepts every measured score.
    assert gate.thresholds["gate-03"] == -math.inf
    assert gate.accepted["gate-03-correct"] is True
    assert gate.accepted["gate-03-error"] is True


def test_tie_break_is_the_median_of_the_tied_thresholds_odd_count():
    # Ascending scores of the other three pairs: W .1, C .2, W .3, C .4, W .5, C .6 -> Youden's J is
    # 1 at exactly three thresholds: .15, .35, .55. The median is .35.
    results = gate_pairs([(0.2, 0.1), (0.4, 0.3), (0.6, 0.5), (0.9, 0.0)])
    gate = metrics.loo_gate(results)
    assert gate.thresholds["gate-04"] == pytest.approx(0.35)


def test_tie_break_is_the_lower_middle_for_an_even_count():
    # Other pairs: W .1, C .3, W .7, C .9 -> J = 0.5 at .2 and .8 only; the lower-middle is .2.
    results = gate_pairs([(0.3, 0.7), (0.9, 0.1), (0.95, 0.05)])
    gate = metrics.loo_gate(results)
    assert gate.thresholds["gate-03"] == pytest.approx(0.2)


def test_candidate_thresholds_include_infinities():
    # Every wrong clip scores above every correct one: J is best (0) at ±inf and negative between.
    results = gate_pairs([(0.1, 0.9), (0.2, 0.8), (0.3, 0.7)])
    gate = metrics.loo_gate(results)
    assert set(gate.thresholds.values()) <= {-math.inf, math.inf}
    assert gate.passed is False


def test_thresholds_and_the_median_match_a_hand_worked_example():
    """Scores are multiples of 1/8, so every midpoint is exact. In eighths the pairs are
    (correct, wrong): gate-01 (6, 3), gate-02 (7, 0), gate-03 (5, 1), gate-04 (2, 4).

    Held out gate-01: the others score C 7 5 2, W 0 1 4; J = 2 at the midpoints 1.5 and 4.5, tied,
    so the lower one, 1.5.  Held out gate-02: C 6 5 2, W 3 1 4; J = 2 at 4.5 alone.
    Held out gate-03: C 6 7 2, W 3 0 4; J = 2 at 5 alone.
    Held out gate-04: C 6 7 5, W 3 0 1 separate; the gap 3..5 has midpoint 4.
    The held-out decisions: gate-01 accepts both clips, gate-02 and gate-03 accept only the correct
    one, gate-04 accepts only the wrong one.
    """
    scores = [(6 / 8, 3 / 8), (7 / 8, 0 / 8), (5 / 8, 1 / 8), (2 / 8, 4 / 8)]
    gate = metrics.loo_gate(gate_pairs(scores))
    assert gate.thresholds == {
        "gate-01": 1.5 / 8,
        "gate-02": 4.5 / 8,
        "gate-03": 5 / 8,
        "gate-04": 4 / 8,
    }
    # Sorted: 1.5/8, 4/8, 4.5/8, 5/8; the middle two are 4/8 and 4.5/8.
    assert gate.median_threshold == 4.25 / 8
    assert [(o.correct_accepted, o.wrong_accepted) for o in gate.outcomes] == [
        (True, True),
        (True, False),
        (True, False),
        (False, True),
    ]
    assert (gate.ca, gate.wa) == (3 / 4, 2 / 4)
    assert (gate.ca_ok, gate.wa_ok, gate.passed) == (False, False, False)


@pytest.mark.parametrize(
    ("thresholds", "median"),
    [
        ([0.3, 0.5, 0.9], 0.5),  # odd: the middle one
        ([0.25, 0.75], 0.5),  # even and finite: the mean of the middle two
        ([-math.inf, 0.5, math.inf], 0.5),  # infinite ends do not matter with an odd count
        ([-math.inf, 0.25, 0.75, math.inf], 0.5),  # ... nor with an even count
        ([-math.inf, -math.inf, 0.5, 0.7], -math.inf),  # an infinite middle: the lower of the two
        ([0.3, 0.5, math.inf, math.inf], 0.5),  # a finite lower middle, an infinite upper
        ([-math.inf, -math.inf, -math.inf], -math.inf),
        ([0.2, math.inf, math.inf], math.inf),
        ([math.inf, math.inf], math.inf),
    ],
)
def test_the_median_threshold_copes_with_infinite_thresholds(thresholds, median):
    gate = metrics.GateMetrics(
        ca=0.0,
        wa=0.0,
        thresholds={f"gate-{i:02d}": theta for i, theta in enumerate(thresholds, start=1)},
        rejected_none=[],
    )
    assert gate.median_threshold == median


def test_outcomes_carry_scores_and_decisions_for_the_report():
    gate = metrics.loo_gate(gate_pairs([(0.6, 0.1), (0.7, 0.2), (0.8, 0.3)]))
    first = gate.outcomes[0]
    assert first.pair == "gate-01"
    assert first.correct_id == "gate-01-correct" and first.wrong_id == "gate-01-error"
    assert (first.correct_overall, first.wrong_overall) == (0.6, 0.1)
    assert first.correct_accepted is True and first.wrong_accepted is False
    assert first.theta == gate.thresholds["gate-01"]


def test_other_sets_are_ignored_by_the_gate():
    results = gate_pairs([(0.6, 0.1), (0.7, 0.2)]) + [
        res("t23-1", 0.0, set="diag_t23", pair="t23-01"),
        res("q-1", 0.0, set="quiet", pair="gate-01"),
    ]
    gate = metrics.loo_gate(results)
    assert len(gate.thresholds) == 2 and gate.passed is True


def test_the_gate_is_deterministic_and_independent_of_result_order():
    results = gate_pairs([(0.6 + 0.02 * i, 0.1 + 0.03 * i) for i in range(8)])
    forward = metrics.loo_gate(results)
    backward = metrics.loo_gate(list(reversed(results)))
    assert forward == backward


@pytest.mark.parametrize("n_pairs", [0, 1])
def test_fewer_than_two_pairs_is_an_error(n_pairs):
    results = gate_pairs([(0.6, 0.1)] * n_pairs)
    with pytest.raises(MetricsError, match="at least 2 gate pairs"):
        metrics.loo_gate(results)


def test_a_pair_needs_one_correct_and_one_tone_error():
    results = gate_pairs([(0.6, 0.1), (0.7, 0.2)])
    missing = [r for r in results if r.id != "gate-02-error"]
    with pytest.raises(MetricsError, match="gate-02.*tone_error"):
        metrics.loo_gate(missing)

    doubled = results + [res("gate-01-again", 0.5, pair="gate-01", label="correct")]
    with pytest.raises(MetricsError, match="gate-01.*more than one"):
        metrics.loo_gate(doubled)

    with pytest.raises(MetricsError, match="gate-x.*no pair"):
        metrics.loo_gate(results + [res("gate-x", 0.5, pair=None)])

    graded = results + [res("gate-03-g", 0.5, pair="gate-03", label="graded")]
    with pytest.raises(MetricsError, match="gate-03-g.*label"):
        metrics.loo_gate(graded)


# ---- diag_minimal and diag_count --------------------------------------------------------------


def test_candidate_id_accuracy_is_the_fraction_ranked_first():
    results = [
        res("m1", 0.5, set="diag_minimal", rank=1),
        res("m2", 0.5, set="diag_minimal", rank=2),
        res("m3", None, set="diag_minimal", rank=1),  # rank counts even when overall is None
        res("m4", 0.5, set="diag_minimal", rank=3),
        res("g1", 0.5, set="gate", rank=2),  # not diag_minimal: ignored
    ]
    assert metrics.candidate_id_accuracy(results) == pytest.approx(2 / 4)


def test_candidate_id_accuracy_without_clips_is_none():
    assert metrics.candidate_id_accuracy([res("g1", 0.5)]) is None


def test_count_robustness_needs_rank_1_and_a_score_at_or_above_theta():
    results = [
        res("c1", 0.7, set="diag_count", rank=1),  # ok
        res("c2", 0.5, set="diag_count", rank=1),  # exactly theta: ok
        res("c3", 0.49, set="diag_count", rank=1),  # below theta
        res("c4", 0.9, set="diag_count", rank=2),  # wrong candidate ranked first
        res("c5", None, set="diag_count", rank=1),  # not measured: a reject
        res("g1", 0.1, set="gate", rank=2),  # ignored
    ]
    assert metrics.count_robustness(results, 0.5) == pytest.approx(2 / 5)


def test_count_robustness_only_applies_theta_to_correct_labels():
    results = [
        res("c1", 0.1, set="diag_count", label="n/a", rank=1),
        res("c2", 0.1, set="diag_count", label="correct", rank=1),
    ]
    assert metrics.count_robustness(results, 0.5) == pytest.approx(1 / 2)


def test_count_robustness_without_clips_is_none():
    assert metrics.count_robustness([res("g1", 0.5)], 0.5) is None


# ---- failures -------------------------------------------------------------------------------


def test_failures_list_gate_misclassifications_then_diag_failures_in_a_stable_order():
    results = gate_pairs([(0.8, 0.2), (0.9, 0.1), (0.45, 0.2), (0.7, 0.3), (0.85, 0.15)])
    results += [
        res("min-2", 0.5, set="diag_minimal", rank=2),
        res("min-1", 0.5, set="diag_minimal", rank=1),
        res("cnt-1", 0.1, set="diag_count", rank=1),
    ]
    gate = metrics.loo_gate(results)
    theta = gate.median_threshold
    failed = metrics.failures(results, gate, theta)
    assert [f.result.id for f in failed] == ["gate-03-correct", "min-2", "cnt-1"]
    assert "rejected" in failed[0].reason and "gate-03" in failed[0].reason
    assert "ranked 2" in failed[1].reason
    assert "below" in failed[2].reason
    assert metrics.failures(list(reversed(results)), gate, theta) == failed


def test_failures_include_accepted_wrong_clips_and_none_scores():
    scores = [(0.6, 0.1), (0.7, 0.2), (None, 0.3), (0.8, 0.95)]
    results = gate_pairs(scores)
    gate = metrics.loo_gate(results)
    failed = {f.result.id: f.reason for f in metrics.failures(results, gate, gate.median_threshold)}
    assert "not measured" in failed["gate-03-correct"]
    assert "accepted" in failed["gate-04-error"]
