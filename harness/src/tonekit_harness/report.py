"""The markdown gate report: the S1 verdict, the numbers behind it and every failing clip."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from .metrics import CA_MIN, WA_MAX

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .clearance import Clearance
    from .evaluate import Result
    from .metrics import Failure, GateMetrics

_MS_DELTAS = {"TurnEarlier", "TurnLater"}  # the other kinds are in Chao units


def num(x: float | None) -> str:
    if x is None:
        return "n/a"
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return f"{x:.3f}"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|")


def rate(value: float | None, n: int | None, *, missing: str = "n/a (no clips)") -> str:
    """A rate as `0.750 (3/4)` out of `n`; `missing` for None."""
    if value is None:
        return missing
    return f"{value:.3f} ({round(value * n)}/{n})" if n else f"{value:.3f}"


def table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return lines


def _delta(kind: str, amount: float) -> str:
    return f"{kind} {amount:.0f} ms" if kind in _MS_DELTAS else f"{kind} {amount:.2f}"


def _deltas(deltas: Sequence[tuple[str, float]]) -> str:
    """The deltas in the order tonekit returns them: at most two, most significant (by z-score)
    first. They are not re-sorted by amount, which mixes ms with Chao units."""
    return ", ".join(_delta(kind, amount) for kind, amount in deltas) or "none"


def _headline(gate: GateMetrics, clearance: Clearance) -> str:
    n = len(gate.thresholds)
    if not clearance.verdict:
        return (
            f"**{clearance.label}**: not a gate verdict, because {clearance.reason}. This run measured "
            f"correct-accept {gate.ca:.3f} and wrong-accept {gate.wa:.3f} over {n} gate pairs; "
            "S1 is measured on real recordings the register allows (spec §9, §13)."
        )
    verdict = "PASS" if gate.passed else "FAIL"
    text = (
        f"**S1: {verdict}** (leave-one-pair-out): correct-accept {gate.ca:.3f} "
        f"(needs at least {float(CA_MIN):.2f}), wrong-accept {gate.wa:.3f} "
        f"(needs at most {float(WA_MAX):.2f}), {n} gate pairs."
    )
    broken = []
    if not gate.ca_ok:
        broken.append("correct-accept is below its bound")
    if not gate.wa_ok:
        broken.append("wrong-accept is above its bound")
    if broken:
        text += " " + " and ".join(broken).capitalize() + "."
    return text


def _metrics_table(
    gate: GateMetrics,
    cand_acc: float | None,
    count_rob: float | None,
    n_minimal: int | None,
    n_count: int | None,
    clearance: Clearance,
) -> list[str]:
    n = len(gate.thresholds)
    # without a verdict the bounds are not applied: a pass or fail here would be one
    ca_result = ("pass" if gate.ca_ok else "fail") if clearance.verdict else "n/a"
    wa_result = ("pass" if gate.wa_ok else "fail") if clearance.verdict else "n/a"
    rows = [
        [
            "Correct-accept (leave-one-pair-out)",
            f"{gate.ca:.3f} ({gate.correct_accepted}/{n})",
            f"at least {float(CA_MIN):.2f}",
            ca_result,
        ],
        [
            "Wrong-accept (leave-one-pair-out)",
            f"{gate.wa:.3f} ({gate.wrong_accepted}/{n})",
            f"at most {float(WA_MAX):.2f}",
            wa_result,
        ],
        ["Candidate-ID accuracy (diag_minimal)", rate(cand_acc, n_minimal), "diagnostic", "-"],
        ["Count robustness (diag_count)", rate(count_rob, n_count), "diagnostic", "-"],
        ["Median threshold over the held-out pairs", num(gate.median_threshold), "-", "-"],
    ]
    return table(["Metric", "Value", "Requirement", "Result"], rows)


def _pair_table(gate: GateMetrics) -> list[str]:
    rows = [
        [
            o.pair,
            num(o.theta),
            num(o.correct_overall),
            "accepted" if o.correct_accepted else "rejected",
            num(o.wrong_overall),
            "accepted" if o.wrong_accepted else "rejected",
        ]
        for o in gate.outcomes
    ]
    header = ["Pair", "Held-out θ", "Correct overall", "Correct", "Wrong overall", "Wrong"]
    return table(header, rows)


def _failure(f: Failure) -> list[str]:
    r: Result = f.result
    lines = [
        f"### {r.id}",
        "",
        f"- {f.reason}",
        f"- set {r.set}, pair {r.pair or 'none'}, label {r.label}, speaker {r.speaker}",
        f"- overall {num(r.overall)}, intended rank {r.intended_rank}, "
        f"margin_llr {num(r.margin_llr)}",
        f"- register {r.register_source}; signal issues: {', '.join(r.issues) or 'none'}",
        "",
    ]
    if r.syllables:
        rows = [
            [
                i,
                s.expected,
                s.heard or "-",
                num(s.p_correct),
                num(s.distance),
                s.measured,
                _deltas(s.deltas),
            ]
            for i, s in enumerate(r.syllables, start=1)
        ]
        header = ["#", "Expected", "Heard", "p_correct", "Distance", "Measured", "Top deltas"]
        lines += table(header, rows) + [""]
    return lines


def write(
    path: str | Path,
    gate: GateMetrics,
    cand_acc: float | None,
    count_rob: float | None,
    failures: Sequence[Failure],
    *,
    clearance: Clearance,
    n_minimal: int | None = None,
    n_count: int | None = None,
    context: Mapping[str, str] | None = None,
) -> None:
    """Write the gate report to `path` (parent directories are created).

    `cand_acc` and `count_rob` are `metrics.candidate_id_accuracy` and `metrics.count_robustness`
    (None when the corpus has no such clips); `n_minimal` and `n_count` are those sets' clip counts,
    shown beside them. `failures` is `metrics.failures(...)`, listed in the order given.
    `clearance` (`clearance.assess`) decides whether the headline is an S1 verdict or says why it
    is not one. `context` (label to text) is printed as a "Run" section. The output depends only
    on the arguments: no timestamps.
    """
    lines = ["# P0 gate report", "", _headline(gate, clearance), ""]
    if context:
        lines += ["## Run", ""] + [f"- {label}: {value}" for label, value in context.items()]
        lines.append("")
    lines += ["## Metrics", ""] + _metrics_table(gate, cand_acc, count_rob, n_minimal, n_count, clearance)
    lines += ["", "## Gate pairs", ""]
    lines += ["Each pair is judged at the threshold fitted on the other pairs.", ""]
    lines += _pair_table(gate) + [""]
    if gate.rejected_none:
        lines += ["## Clips with no score", ""]
        lines += ["Tone not checked (no syllable measured); each counts as a reject.", ""]
        lines += [f"- {cid}" for cid in gate.rejected_none] + [""]
    lines += ["## Failures", ""]
    if failures:
        for f in failures:
            lines += _failure(f)
    else:
        lines += ["None.", ""]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
