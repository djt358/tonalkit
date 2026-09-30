"""`tkh bakeoff`: tonekit's pYIN against SwiftF0 as the runtime f0 (spec §4, §10).

Two questions, each answered per provider:

- **f0 accuracy under noise**, on the clips of a `tkh synth` directory, against the exact f0 truth
  WORLD was given (`pitch_metrics`: GPE and VDE, frames pooled per condition, see `conditions`).
- **the S1 gate**, on a corpus manifest with gate pairs: `evaluate.run` with each provider's f0,
  then `metrics.loo_gate`.

`bakeoff_report` writes what came out; nothing here decides which provider tonekit uses.
The brief's `swiftf0_track`, `gpe` and `vde` are re-exported.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, replace
from importlib import metadata
from pathlib import Path

import numpy as np

from . import bakeoff_report, conditions, corpus, evaluate, manifest, metrics, pitch_tracks
from .family import SynthError
from .manifest import Clip, ManifestError
from .metrics import GateMetrics
from .pitch_metrics import Counts, count
from .pitch_metrics import gpe, vde  # noqa: F401  (re-exported: `bakeoff.gpe`, `bakeoff.vde`)
from .pitch_tracks import swiftf0_track  # noqa: F401  (re-exported: `bakeoff.swiftf0_track`)

# The providers the gate grades, report name -> the `f0` argument of `evaluate.run` (None: tonekit's
# own pYIN): each one's f0 goes through the whole pipeline.
PROVIDERS: dict[str, str | None] = {"pyin": None, "swift-f0": "swift-f0"}

SWIFT_REPAIRED = "swift-f0 (after tonekit's octave repair)"
# What the synthetic section measures, in report order: report name -> (f0 provider, where the track
# is read). "analysis" is the f0 tonekit ends up with, from the Analysis it made with that provider
# (after octave repair); "handed" is the provider's own track as it is handed to tonekit.
MEASURES: dict[str, tuple[str | None, str]] = {
    "pyin": (None, "analysis"),
    "swift-f0": ("swift-f0", "handed"),
    SWIFT_REPAIRED: ("swift-f0", "analysis"),
}


class BakeoffError(ValueError):
    """The bakeoff cannot run on what it was given."""


@dataclass(frozen=True)
class Group:
    """The clips of one condition: how many, and each measurement's pooled error counts."""

    clips: int
    counts: dict[str, Counts]


@dataclass(frozen=True)
class GateScores:
    """One provider's S1 gate: the metrics, and `diag_minimal` candidate-ID accuracy (None when
    the manifest has no such clip, `n_minimal` of them otherwise)."""

    metrics: GateMetrics
    candidate_id: float | None
    n_minimal: int


@dataclass(frozen=True)
class Bakeoff:
    """What a run measured: per condition (`clean` first, then noise by SNR) and per provider;
    None for a part that was not run."""

    synthetic: dict[str, Group] | None
    gate: dict[str, GateScores] | None


# ---- running -----------------------------------------------------------------------------------


def require_input(synthetic: object, gate: object) -> None:
    if synthetic is None and gate is None:
        raise BakeoffError("give --synthetic and/or --gate")


def _track(
    measure: tuple[str | None, str],
    graders: dict[str | None, evaluate.Grader],
    clip: Clip,
    audio: tuple[bytes, np.ndarray],
) -> list[float | None]:
    """One measurement's f0 for a clip (see `MEASURES`); `audio` is the clip's `read_wav`."""
    f0, where = measure
    if where == "analysis":
        return pitch_tracks.pyin_track(graders[f0].analysis(clip, None, audio))
    try:
        return pitch_tracks.track_hz(pitch_tracks.provider_track(f0, audio[1]))
    except ValueError as e:
        raise evaluate.EvalError(f"{clip.id}: {e}") from e


def _synthetic(
    directory: Path, pack_toml: str, calib_json: str | None, accent: str | None, cache_dir
) -> dict[str, Group]:
    clips = manifest.load(directory / "manifest.jsonl")
    if not clips:
        raise BakeoffError(f"{directory / 'manifest.jsonl'} has no clips")
    truth = corpus.read_truth(directory)
    grader = evaluate.Grader(
        pack_toml, calib_json, accent or evaluate.base_accent(pack_toml), directory, cache_dir
    )
    graders = {f0: replace(grader, f0=f0) for f0, _ in MEASURES.values()}
    sizes: dict[str, int] = {}
    pooled: dict[str, dict[str, Counts]] = {}
    for clip in clips:
        if clip.id not in truth:
            raise BakeoffError(f"{clip.id}: no f0 truth in {directory / 'truth.jsonl'}")
        audio = evaluate.read_wav(directory / clip.path, clip.id)
        name = conditions.condition(clip)
        sizes[name] = sizes.get(name, 0) + 1
        totals = pooled.setdefault(name, {measure: Counts() for measure in MEASURES})
        for measure, how in MEASURES.items():
            est = _track(how, graders, clip, audio)
            try:
                totals[measure] += count(est, truth[clip.id])
            except ValueError as e:  # the truth has another length
                raise BakeoffError(f"{clip.id}: {e}") from e
    return {name: Group(sizes[name], pooled[name]) for name in sorted(pooled, key=conditions.order)}


def _gate(
    manifest_path: Path, pack_toml: str, calib_json: str | None, accent: str | None, cache_dir
) -> dict[str, GateScores]:
    clips = manifest.load(manifest_path)
    n_minimal = sum(c.set == "diag_minimal" for c in clips)
    scores = {}
    for provider, f0 in PROVIDERS.items():
        results = evaluate.run(
            clips,
            pack_toml,
            calib_json,
            accent,
            root=manifest_path.parent,
            cache_dir=cache_dir,
            use_cache=cache_dir is not None,
            f0=f0,
        )
        scores[provider] = GateScores(
            metrics.loo_gate(results), metrics.candidate_id_accuracy(results), n_minimal
        )
    return scores


def run(
    *,
    synthetic: str | Path | None = None,
    gate: str | Path | None = None,
    pack_toml: str,
    calib_json: str | None,
    accent: str | None = None,
    cache_dir: str | Path | None = None,
    use_cache: bool = True,
) -> Bakeoff:
    """Measure each provider on the `tkh synth` directory `synthetic` and/or grade the gate
    manifest `gate` with it. Analyses are cached like `evaluate.run`'s (`cache_dir`, `use_cache`).

    Raises `BakeoffError` if neither is given, a clip has no f0 truth or a truth of the wrong
    length; `EvalError`, `ManifestError`, `SynthError`, `MetricsError` and `OSError` as the
    modules underneath do."""
    require_input(synthetic, gate)
    cache = (Path(cache_dir or evaluate.DEFAULT_CACHE_DIR)) if use_cache else None
    return Bakeoff(
        synthetic=(
            None
            if synthetic is None
            else _synthetic(Path(synthetic), pack_toml, calib_json, accent, cache)
        ),
        gate=(None if gate is None else _gate(Path(gate), pack_toml, calib_json, accent, cache)),
    )


# ---- tkh bakeoff -------------------------------------------------------------------------------


def _context(args: argparse.Namespace) -> dict[str, str]:
    context = {}
    if args.synthetic:
        context["synthetic corpus"] = str(args.synthetic)
    if args.gate:
        context["gate manifest"] = str(args.gate)
    onnx = metadata.version("onnxruntime")
    swift = f"{pitch_tracks.provider_identity('swift-f0')} on onnxruntime {onnx}"
    context |= {
        "pack": str(args.pack),
        "calibration": str(args.calib) if args.calib else "the pack's own",
        "accent": args.accent or "the pack's base accent",
        "providers": f"pyin (tonekit's own); {swift}",
        "tonekit-py": evaluate.tonekit_py_version(),
    }
    return context


def _summary(result: Bakeoff, report_path: str) -> str:
    parts = []
    if result.synthetic is not None:
        clips = sum(group.clips for group in result.synthetic.values())
        parts.append(f"{clips} synthetic clip{'' if clips == 1 else 's'}")
    if result.gate is not None:
        verdicts = ", ".join(
            f"{provider} {'PASS' if s.metrics.passed else 'FAIL'} "
            f"(CA {s.metrics.ca:.3f}, WA {s.metrics.wa:.3f})"
            for provider, s in result.gate.items()
        )
        parts.append(f"S1: {verdicts}")
    return f"bakeoff: {'; '.join(parts)}; report written to {report_path}"


def _run(args: argparse.Namespace) -> int:
    try:
        require_input(args.synthetic, args.gate)
        pack_toml = Path(args.pack).read_text(encoding="utf-8")
        calib_json = Path(args.calib).read_text(encoding="utf-8") if args.calib else None
        result = run(
            synthetic=args.synthetic,
            gate=args.gate,
            pack_toml=pack_toml,
            calib_json=calib_json,
            accent=args.accent,
            use_cache=not args.no_cache,
        )
        bakeoff_report.write(args.report, result, context=_context(args))
    except (
        BakeoffError,
        ManifestError,
        evaluate.EvalError,
        SynthError,
        metrics.MetricsError,
        OSError,
    ) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(_summary(result, args.report))
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "bakeoff",
        help="compare tonekit's pYIN with SwiftF0: f0 accuracy on synthetic clips, and the S1 gate",
    )
    p.add_argument(
        "--synthetic", help="a `tkh synth` output directory (manifest.jsonl and truth.jsonl)"
    )
    p.add_argument("--gate", help="a corpus manifest (JSONL) with gate pairs, e.g. the DJ corpus")
    p.add_argument("--pack", required=True, help="language pack TOML (e.g. packs/cmn/cmn.toml)")
    p.add_argument("--calib", help="calibration JSON (default: the pack's own)")
    p.add_argument("--accent", help="accent to grade against (default: the pack's base accent)")
    p.add_argument("--report", required=True, help="markdown report to write")
    p.add_argument(
        "--no-cache", action="store_true", help="neither read nor write the analysis cache"
    )
    p.set_defaults(func=_run)
