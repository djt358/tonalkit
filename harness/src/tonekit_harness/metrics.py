"""Gate metrics over evaluation `Result`s.

The P0 gate S1: pick the accept threshold by leave-one-pair-out (LOO) and require correct-accept
at least 0.90 and wrong-accept at most 0.10. The utterance score is `Result.overall`; a clip with
no score (`None`, "tone not checked") is a reject at every threshold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .evaluate import Result

CA_MIN = Fraction(9, 10)  # gate S1: correct-accept at least this ...
WA_MAX = Fraction(1, 10)  # ... and wrong-accept at most this

_FAILURE_SET_ORDER = {"gate": 0, "diag_minimal": 1, "diag_count": 2}


class MetricsError(ValueError):
    """The results cannot be scored (too few gate pairs, a malformed pair, ...)."""


@dataclass(frozen=True)
class PairOutcome:
    """One gate pair judged at the threshold fitted on all the other pairs."""

    pair: str
    theta: float
    correct_id: str
    correct_overall: float | None
    correct_accepted: bool
    wrong_id: str
    wrong_overall: float | None
    wrong_accepted: bool


@dataclass(frozen=True)
class GateMetrics:
    ca: float  # correct clips accepted / all correct clips
    wa: float  # wrong (tone_error) clips accepted / all wrong clips
    thresholds: dict[str, float]  # held-out pair id -> θ fitted on the other pairs; may be ±inf
    rejected_none: list[str]  # clip ids with no score, counted as rejects
    outcomes: list[PairOutcome] = field(default_factory=list)  # sorted by pair id

    @property
    def correct_accepted(self) -> int:
        """How many held-out correct clips were accepted (one per pair at most)."""
        return sum(o.correct_accepted for o in self.outcomes)

    @property
    def wrong_accepted(self) -> int:
        """How many held-out wrong clips were accepted (one per pair at most)."""
        return sum(o.wrong_accepted for o in self.outcomes)

    @property
    def ca_ok(self) -> bool:
        """Correct-accept is at least `CA_MIN`, decided exactly from the counts: the float `ca`
        can sit a rounding error either side of a bound (2/20 as a float is above 1/10)."""
        return Fraction(self.correct_accepted, len(self.outcomes)) >= CA_MIN

    @property
    def wa_ok(self) -> bool:
        """Wrong-accept is at most `WA_MAX`, decided exactly from the counts."""
        return Fraction(self.wrong_accepted, len(self.outcomes)) <= WA_MAX

    @property
    def passed(self) -> bool:
        """Gate S1: both bounds hold."""
        return self.ca_ok and self.wa_ok

    @property
    def median_threshold(self) -> float:
        """The median of the LOO thresholds (the mean of the middle two when there is an even
        number and both are finite, otherwise the lower of them)."""
        ordered = sorted(self.thresholds.values())
        n = len(ordered)
        lower, upper = ordered[(n - 1) // 2], ordered[n // 2]
        if math.isfinite(lower) and math.isfinite(upper):
            return (lower + upper) / 2
        return lower

    @property
    def accepted(self) -> dict[str, bool]:
        """Clip id -> accepted at its held-out threshold, for every gate clip."""
        out: dict[str, bool] = {}
        for o in self.outcomes:
            out[o.correct_id] = o.correct_accepted
            out[o.wrong_id] = o.wrong_accepted
        return out


@dataclass(frozen=True)
class Failure:
    result: Result
    reason: str


def _accepts(score: float | None, theta: float) -> bool:
    return score is not None and score >= theta


def _gate_pairs(results: Sequence[Result]) -> list[tuple[str, Result, Result]]:
    """The gate results grouped by pair, as (pair, correct, wrong) sorted by pair id."""
    by_pair: dict[str, dict[str, Result]] = {}
    for r in results:
        if r.set != "gate":
            continue
        if r.pair is None:
            raise MetricsError(f"gate clip {r.id!r} has no pair")
        if r.label not in ("correct", "tone_error"):
            raise MetricsError(
                f"gate clip {r.id!r} has label {r.label!r}; expected 'correct' or 'tone_error'"
            )
        slot = by_pair.setdefault(r.pair, {})
        if r.label in slot:
            raise MetricsError(
                f"gate pair {r.pair!r} has more than one {r.label!r} clip "
                f"({slot[r.label].id!r} and {r.id!r})"
            )
        slot[r.label] = r
    pairs = []
    for pair in sorted(by_pair):
        slot = by_pair[pair]
        for label in ("correct", "tone_error"):
            if label not in slot:
                raise MetricsError(f"gate pair {pair!r} has no {label!r} clip")
        pairs.append((pair, slot["correct"], slot["tone_error"]))
    return pairs


def _fit_threshold(correct: Sequence[float | None], wrong: Sequence[float | None]) -> float:
    """The θ maximising Youden's J = CA − WA on these (equally many) correct and wrong scores.

    Candidates are -inf, +inf and the midpoints between consecutive sorted unique measured scores;
    a clip is accepted iff its score is at least θ. Ties go to the median of the tied θs, taking
    the lower middle when their number is even.
    """
    measured = sorted({s for s in (*correct, *wrong) if s is not None})
    candidates = [-math.inf, *((a + b) / 2 for a, b in zip(measured, measured[1:])), math.inf]
    # Both lists have the same length, so J's numerator, accepted-correct minus accepted-wrong,
    # ranks θs exactly (integers, no float ties).
    gains = [
        sum(_accepts(s, theta) for s in correct) - sum(_accepts(s, theta) for s in wrong)
        for theta in candidates
    ]
    best = max(gains)
    tied = [theta for theta, gain in zip(candidates, gains) if gain == best]
    return tied[(len(tied) - 1) // 2]


def loo_gate(results: Sequence[Result]) -> GateMetrics:
    """Gate S1 over the `gate` results by leave-one-pair-out.

    For each held-out pair, θ is fitted on the other pairs (`_fit_threshold`) and applied to the
    held-out pair. CA and WA aggregate the held-out decisions over all pairs; `passed` is
    CA ≥ 0.90 and WA ≤ 0.10, compared exactly on the counts (`GateMetrics.ca_ok`, `wa_ok`).
    Raises `MetricsError` for fewer than 2 pairs or a malformed pair.
    """
    pairs = _gate_pairs(results)
    if len(pairs) < 2:
        raise MetricsError(
            f"leave-one-pair-out needs at least 2 gate pairs; the results have {len(pairs)}"
        )
    outcomes: list[PairOutcome] = []
    for i, (pair, correct, wrong) in enumerate(pairs):
        others = pairs[:i] + pairs[i + 1 :]
        theta = _fit_threshold([c.overall for _, c, _ in others], [w.overall for _, _, w in others])
        outcomes.append(
            PairOutcome(
                pair=pair,
                theta=theta,
                correct_id=correct.id,
                correct_overall=correct.overall,
                correct_accepted=_accepts(correct.overall, theta),
                wrong_id=wrong.id,
                wrong_overall=wrong.overall,
                wrong_accepted=_accepts(wrong.overall, theta),
            )
        )
    n = len(pairs)
    rejected_none = sorted(
        r.id for _, c, w in pairs for r in (c, w) if r.overall is None
    )
    return GateMetrics(
        ca=sum(o.correct_accepted for o in outcomes) / n,
        wa=sum(o.wrong_accepted for o in outcomes) / n,
        thresholds={o.pair: o.theta for o in outcomes},
        rejected_none=rejected_none,
        outcomes=outcomes,
    )


def candidate_id_accuracy(results: Sequence[Result]) -> float | None:
    """The fraction of `diag_minimal` clips whose intended reading ranks first, or None if the
    results have no such clip."""
    clips = [r for r in results if r.set == "diag_minimal"]
    if not clips:
        return None
    return sum(r.intended_rank == 1 for r in clips) / len(clips)


def _count_ok(r: Result, theta: float) -> bool:
    return r.intended_rank == 1 and (r.label != "correct" or _accepts(r.overall, theta))


def count_robustness(results: Sequence[Result], theta: float) -> float | None:
    """The fraction of `diag_count` clips ranked first and, for a `correct` clip, scoring at least
    `theta` (normally the median LOO threshold); None if the results have no such clip."""
    clips = [r for r in results if r.set == "diag_count"]
    if not clips:
        return None
    return sum(_count_ok(r, theta) for r in clips) / len(clips)


def _fmt(x: float | None) -> str:
    return "not measured" if x is None else f"{x:.3f}"


def _gate_reason(r: Result, gate: GateMetrics) -> str | None:
    """Why the gate counts `r` against us, or None if its held-out decision was right."""
    if r.pair is None or r.id not in gate.accepted:
        return None
    accepted = gate.accepted[r.id]
    where = f"overall {_fmt(r.overall)}, held-out θ {gate.thresholds[r.pair]:.3f}, pair {r.pair}"
    if r.label == "correct" and not accepted:
        return f"correct clip rejected ({where})"
    if r.label == "tone_error" and accepted:
        return f"tone-error clip accepted ({where})"
    return None


def _diag_reason(r: Result, theta: float) -> str | None:
    if r.set == "diag_minimal" and r.intended_rank != 1:
        return f"intended reading ranked {r.intended_rank}, expected rank 1"
    if r.set == "diag_count" and not _count_ok(r, theta):
        if r.intended_rank != 1:
            return f"intended reading ranked {r.intended_rank}, expected rank 1"
        return f"overall {_fmt(r.overall)}, below the median threshold {theta:.3f}"
    return None


def failures(results: Sequence[Result], gate: GateMetrics, theta: float) -> list[Failure]:
    """Every clip the metrics count against us, with why: gate clips misclassified at their
    held-out θ, `diag_minimal` clips whose intended reading did not rank first and `diag_count`
    clips that fail `count_robustness` at `theta`. Ordered gate, diag_minimal, diag_count, then
    by pair and clip id, whatever the order of `results`."""
    out = []
    for r in results:
        reason = _gate_reason(r, gate) if r.set == "gate" else _diag_reason(r, theta)
        if reason is not None:
            out.append(Failure(r, reason))
    out.sort(key=lambda f: (_FAILURE_SET_ORDER[f.result.set], f.result.pair or "", f.result.id))
    return out
