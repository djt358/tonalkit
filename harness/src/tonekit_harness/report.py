"""The markdown gate report: the S1 verdict, the numbers behind it and every failing clip."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from .metrics import CA_MIN, WA_MAX

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .evaluate import Result
    from .metrics import Failure, GateMetrics

_TOP_DELTAS = 2
_MS_DELTAS = {"TurnEarlier", "TurnLater"}  # the other kinds are in Chao units


def _num(x: float | None) -> str:
    if x is None:
        return "n/a"
    if math.isinf(x):
        return "inf" if x > 0 else "-inf"
    return f"{x:.3f}"


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|")


def _rate(rate: float | None, n: int | None) -> str:
    if rate is None:
        return "n/a (no clips)"
    return f"{rate:.3f} ({round(rate * n)}/{n})" if n else f"{rate:.3f}"


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return lines


def _delta(kind: str, amount: float) -> str:
    return f"{kind} {amount:.0f} ms" if kind in _MS_DELTAS else f"{kind} {amount:.2f}"


def _top_deltas(deltas: Sequence[tuple[str, float]]) -> str:
    top = sorted(deltas, key=lambda d: (-abs(d[1]), d[0]))[:_TOP_DELTAS]
    return ", ".join(_delta(kind, amount) for kind, amount in top) or "none"


def _headline(gate: GateMetrics) -> str:
    n = len(gate.thresholds)
    verdict = "PASS" if gate.passed else "FAIL"
    text = (
        f"**S1: {verdict}** (leave-one-pair-out): correct-accept {gate.ca:.3f} "
        f"(needs at least {float(CA_MIN):.2f}), wrong-accept {gate.wa:.3f} "
        f"(needs at most {float(WA_MAX):.2f}), {n} gate pairs."
    )
    broken = []
    if gate.ca < CA_MIN:
        broken.append("correct-accept is below its bound")
    if gate.wa > WA_MAX:
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
) -> list[str]:
    n = len(gate.thresholds)
    accepted_correct = sum(o.correct_accepted for o in gate.outcomes)
    accepted_wrong = sum(o.wrong_accepted for o in gate.outcomes)
    ca_ok, wa_ok = gate.ca >= CA_MIN, gate.wa <= WA_MAX
    rows = [
        [
            "Correct-accept (leave-one-pair-out)",
            f"{gate.ca:.3f} ({accepted_correct}/{n})",
            f"at least {float(CA_MIN):.2f}",
            "pass" if ca_ok else "fail",
        ],
        [
            "Wrong-accept (leave-one-pair-out)",
            f"{gate.wa:.3f} ({accepted_wrong}/{n})",
            f"at most {float(WA_MAX):.2f}",
            "pass" if wa_ok else "fail",
        ],
        ["Candidate-ID accuracy (diag_minimal)", _rate(cand_acc, n_minimal), "diagnostic", "-"],
        ["Count robustness (diag_count)", _rate(count_rob, n_count), "diagnostic", "-"],
        ["Median threshold over the held-out pairs", _num(gate.median_threshold), "-", "-"],
    ]
    return _table(["Metric", "Value", "Requirement", "Result"], rows)


def _pair_table(gate: GateMetrics) -> list[str]:
    rows = [
        [
            o.pair,
            _num(o.theta),
            _num(o.correct_overall),
            "accepted" if o.correct_accepted else "rejected",
            _num(o.wrong_overall),
            "accepted" if o.wrong_accepted else "rejected",
        ]
        for o in gate.outcomes
    ]
    header = ["Pair", "Held-out θ", "Correct overall", "Correct", "Wrong overall", "Wrong"]
    return _table(header, rows)


def _failure(f: Failure) -> list[str]:
    r: Result = f.result
    lines = [
        f"### {r.id}",
        "",
        f"- {f.reason}",
        f"- set {r.set}, pair {r.pair or 'none'}, label {r.label}, speaker {r.speaker}",
        f"- overall {_num(r.overall)}, intended rank {r.intended_rank}, "
        f"margin_llr {_num(r.margin_llr)}",
        f"- register {r.register_source}; signal issues: {', '.join(r.issues) or 'none'}",
        "",
    ]
    if r.syllables:
        rows = [
            [
                i,
                s.expected,
                s.heard or "-",
                _num(s.p_correct),
                _num(s.distance),
                s.measured,
                _top_deltas(s.deltas),
            ]
            for i, s in enumerate(r.syllables, start=1)
        ]
        header = ["#", "Expected", "Heard", "p_correct", "Distance", "Measured", "Top deltas"]
        lines += _table(header, rows) + [""]
    return lines


def write(
    path: str | Path,
    gate: GateMetrics,
    cand_acc: float | None,
    count_rob: float | None,
    failures: Sequence[Failure],
    *,
    n_minimal: int | None = None,
    n_count: int | None = None,
    context: Mapping[str, str] | None = None,
) -> None:
    """Write the gate report to `path` (parent directories are created).

    `cand_acc` and `count_rob` are `metrics.candidate_id_accuracy` and `metrics.count_robustness`
    (None when the corpus has no such clips); `n_minimal` and `n_count` are those sets' clip counts,
    shown beside them. `failures` is `metrics.failures(...)`, listed in the order given.
    `context` (label to value) is printed as a "Run" section. The output depends only on the
    arguments: no timestamps.
    """
    lines = ["# P0 gate report", "", _headline(gate), ""]
    if context:
        lines += ["## Run", ""] + [f"- {label}: `{value}`" for label, value in context.items()]
        lines.append("")
    lines += ["## Metrics", ""] + _metrics_table(gate, cand_acc, count_rob, n_minimal, n_count)
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
