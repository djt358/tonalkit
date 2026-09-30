"""The bakeoff markdown: f0 accuracy per noise condition and the S1 gate metrics, one row per
provider. It states what the numbers show and decides nothing. The output depends only on the
arguments: no timestamps."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from . import report
from .metrics import CA_MIN, WA_MAX

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .bakeoff import Bakeoff, GateScores, Group

_METHOD = (
    "Each clip's f0 is compared frame by frame, on tonekit's 10 ms grid, with the exact f0 that "
    "WORLD was given. **pyin** is tonekit's own track as its Analysis holds it, after octave "
    "repair (the raw pYIN track is not exposed to Python). **swift-f0** is SwiftF0's track "
    "searched over 50-600 Hz and resampled onto the grid as tonekit receives it, before octave "
    "repair: a grid frame is voiced where the interpolated confidence is at least 0.9. GPE is "
    "the fraction of frames voiced in both whose pitch is more than 20% off; VDE is the "
    "fraction of all frames whose voicing differs. Frames are pooled over the clips of a "
    "condition. A noise clip is in the bucket of its SNR (`noise ~N dB`, the nearest of 5, 10 "
    "and 20 dB); every other clip is clean."
)


def _rate(rate: float | None, numerator: int, denominator: int) -> str:
    return "n/a" if rate is None else f"{rate:.3f} ({numerator}/{denominator})"


def _lower_gpe(synthetic: Mapping[str, Group]) -> str:
    """Which provider has the lower GPE in each condition: its name, `tie`, or `n/a` when a
    provider has no frame voiced in both."""
    parts = []
    for name, group in synthetic.items():
        rates = {provider: counts.gpe for provider, counts in group.counts.items()}
        if any(rate is None for rate in rates.values()):
            verdict = "n/a"
        else:
            best = min(rates.values())
            winners = [provider for provider, rate in rates.items() if rate == best]
            verdict = winners[0] if len(winners) == 1 else "tie"
        parts.append(f"{name} {verdict}")
    return "Lower GPE, by condition: " + "; ".join(parts) + "."


def _synthetic_section(synthetic: Mapping[str, Group]) -> list[str]:
    rows = []
    for name, group in synthetic.items():
        for provider, c in group.counts.items():
            rows.append(
                [
                    name,
                    group.clips,
                    provider,
                    c.frames,
                    c.both_voiced,
                    _rate(c.gpe, c.gross_errors, c.both_voiced),
                    _rate(c.vde, c.voicing_errors, c.frames),
                ]
            )
    header = ["Condition", "Clips", "Provider", "Frames", "Voiced in both", "GPE", "VDE"]
    return [
        "## Synthetic f0 accuracy",
        "",
        _METHOD,
        "",
        *report.table(header, rows),
        "",
        _lower_gpe(synthetic),
        "",
    ]


def _gate_row(provider: str, scores: GateScores) -> list[object]:
    gate = scores.metrics
    n = len(gate.thresholds)
    return [
        provider,
        report.rate(gate.ca, n),
        report.rate(gate.wa, n),
        "PASS" if gate.passed else "FAIL",
        report.num(gate.median_threshold),
        report.rate(scores.candidate_id, scores.n_minimal),
    ]


def _gate_section(gate: Mapping[str, GateScores]) -> list[str]:
    n = len(next(iter(gate.values())).metrics.thresholds)
    header = [
        "Provider",
        "Correct-accept",
        "Wrong-accept",
        "S1",
        "Median threshold",
        "Candidate-ID accuracy",
    ]
    verdict = ", ".join(
        f"{provider} {'PASS' if scores.metrics.passed else 'FAIL'}"
        for provider, scores in gate.items()
    )
    return [
        "## Gate S1",
        "",
        f"Each provider's f0 goes through the whole pipeline on the same {n} gate pairs. "
        f"S1 needs leave-one-pair-out correct-accept of at least {float(CA_MIN):.2f} and "
        f"wrong-accept of at most {float(WA_MAX):.2f}.",
        "",
        *report.table(header, [_gate_row(provider, scores) for provider, scores in gate.items()]),
        "",
        f"S1 (leave-one-pair-out): {verdict}.",
        "",
    ]


def write(path: str | Path, result: Bakeoff, *, context: Mapping[str, str] | None = None) -> None:
    """Write the bakeoff report to `path` (parent directories are created). `context` (label to
    text) is printed as a "Run" section. Only the sections `result` has are written."""
    lines = [
        "# P0 f0 bakeoff: pYIN against SwiftF0",
        "",
        "Observations from one run, not a decision.",
        "",
    ]
    if context:
        lines += ["## Run", ""] + [f"- {label}: {value}" for label, value in context.items()]
        lines.append("")
    if result.synthetic is not None:
        lines += _synthetic_section(result.synthetic)
    if result.gate is not None:
        lines += _gate_section(result.gate)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
