"""The bakeoff markdown: f0 accuracy per noise condition and the S1 gate metrics, one row per
provider. It states what the numbers show and decides nothing. The output depends only on the
arguments: no timestamps."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from . import conditions, pitch_metrics, pitch_tracks, report
from .metrics import CA_MIN, WA_MAX

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from .bakeoff import Bakeoff, GateScores, Group
    from .pitch_metrics import Counts


def _method() -> str:
    return (
        "Each clip's f0 is compared frame by frame, on tonekit's 10 ms grid, with the exact f0 "
        "that WORLD was given. **pyin** is tonekit's own track as its Analysis holds it, after "
        "octave repair (the raw pYIN track is not exposed to Python). **swift-f0** is SwiftF0's "
        f"track searched over {pitch_tracks.F0_MIN_HZ:g}-{pitch_tracks.F0_MAX_HZ:g} Hz and "
        "resampled onto the grid as tonekit receives it, before octave repair: a grid frame is "
        f"voiced where the interpolated confidence is at least {pitch_tracks.GRID_VOICED:g}. "
        f"A clip peaking below {pitch_tracks.QUIET_PEAK_DBFS:g} dBFS is scaled up to a peak of "
        f"{pitch_tracks.QUIET_TARGET_PEAK:g} before SwiftF0 sees it (its README's rule); tonekit "
        "always gets the original samples. **swift-f0 (after tonekit's octave repair)** is the "
        "f0 tonekit ends up with when it is handed that track, so it compares with pyin like for "
        "like. GPE is the fraction of frames voiced in both whose pitch is more than "
        f"{pitch_metrics.GROSS_ERROR:.0%} off; VDE is the fraction of all frames whose voicing "
        "differs. GPE is conditional on each provider's own voicing: a provider that is voiced "
        "on fewer frames is judged on fewer, so read it with the Voiced in both column. Frames "
        "are pooled over the clips of a condition. A noise clip is in the bucket of its SNR "
        f"(`noise ~N dB`, the nearest of {conditions.buckets_text()}); every other clip is clean."
    )


def _lower(synthetic: Mapping[str, Group], metric: str, rate: Callable[[Counts], float | None]):
    """Which measurement has the lower `metric` in each condition: its name (`a and b` when they
    share the lowest), `tie` when all do, or `n/a` when one has no frames to judge."""
    parts = []
    for name, group in synthetic.items():
        rates = {measure: rate(counts) for measure, counts in group.counts.items()}
        if any(r is None for r in rates.values()):
            verdict = "n/a"
        else:
            best = min(rates.values())
            winners = [measure for measure, r in rates.items() if r == best]
            verdict = "tie" if len(winners) == len(rates) else " and ".join(winners)
        parts.append(f"{name} {verdict}")
    return f"Lower {metric}, by condition: " + "; ".join(parts) + "."


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
                    report.rate(c.gpe, c.both_voiced, missing="n/a"),
                    report.rate(c.vde, c.frames, missing="n/a"),
                ]
            )
    header = ["Condition", "Clips", "Provider", "Frames", "Voiced in both", "GPE", "VDE"]
    return [
        "## Synthetic f0 accuracy",
        "",
        _method(),
        "",
        *report.table(header, rows),
        "",
        _lower(synthetic, "GPE", lambda c: c.gpe),
        "",
        _lower(synthetic, "VDE", lambda c: c.vde),
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
