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
from collections.abc import Mapping
from dataclasses import dataclass, replace
from importlib import metadata
from pathlib import Path

import numpy as np

from . import (
    bakeoff_report,
    calibration,
    clearance,
    conditions,
    corpus,
    evaluate,
    manifest,
    metrics,
    pitch_tracks,
    provenance,
)
from .clearance import Clearance
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
    None for a part that was not run. `clearance` says whether the gate part may claim an S1
    verdict (required when there is a gate part)."""

    synthetic: dict[str, Group] | None
    gate: dict[str, GateScores] | None
    clearance: Clearance | None = None


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
    manifest_path: Path,
    pack_toml: str,
    calib_json: str | None,
    accent: str | None,
    cache_dir,
    register: Mapping[str, str],
    allow_synthetic: bool,
) -> tuple[dict[str, GateScores], Clearance]:
    clips = manifest.load(manifest_path, register=register)
    cleared = clearance.assess(clips, register, allow_synthetic=allow_synthetic)
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
    return scores, cleared


def run(
    *,
    synthetic: str | Path | None = None,
    gate: str | Path | None = None,
    pack_toml: str,
    calib_json: str | None,
    accent: str | None = None,
    cache_dir: str | Path | None = None,
    use_cache: bool = True,
    register: Mapping[str, str] | None = None,
    allow_synthetic: bool = False,
) -> Bakeoff:
    """Measure each provider on the `tkh synth` directory `synthetic` and/or grade the gate
    manifest `gate` with it. Analyses are cached like `evaluate.run`'s (`cache_dir`, `use_cache`).

    A gate run needs the data `register` (`provenance.load_register`): every clip's source must be
    one of its ids, and the result's `clearance` says whether the gate may claim an S1 verdict
    (real recordings the register allows) or not (synthetic or non-allowed clips; with
    `allow_synthetic`, synthetic clips make a smoke run).

    Raises `BakeoffError` if neither is given, a gate run has no register, a clip has no f0 truth
    or a truth of the wrong length; `EvalError`, `ManifestError`, `SynthError`, `MetricsError` and
    `OSError` as the modules underneath do."""
    require_input(synthetic, gate)
    if gate is not None and register is None:
        raise BakeoffError("a gate run needs the data register (--register)")
    cache = (Path(cache_dir or evaluate.DEFAULT_CACHE_DIR)) if use_cache else None
    scores, cleared = (
        (None, None)
        if gate is None
        else _gate(Path(gate), pack_toml, calib_json, accent, cache, register, allow_synthetic)
    )
    return Bakeoff(
        synthetic=(
            None
            if synthetic is None
            else _synthetic(Path(synthetic), pack_toml, calib_json, accent, cache)
        ),
        gate=scores,
        clearance=cleared,
    )


# ---- tkh bakeoff -------------------------------------------------------------------------------


def _context(args: argparse.Namespace, files: calibration.PackFiles) -> dict[str, str]:
    context = {}
    if args.synthetic:
        context["synthetic corpus"] = str(args.synthetic)
    if args.gate:
        context["gate manifest"] = str(args.gate)
        context["data register"] = str(args.register or clearance.default_register())
    onnx = metadata.version("onnxruntime")
    swift = f"{pitch_tracks.provider_identity('swift-f0')} on onnxruntime {onnx}"
    context |= {
        **files.context(),
        "accent": args.accent or "the pack's base accent",
        "providers": f"pyin (tonekit's own); {swift}",
        "tonekit-py": evaluate.tonekit_py_fingerprint(),
    }
    return context


def _summary(result: Bakeoff, report_path: str) -> str:
    parts = []
    if result.synthetic is not None:
        clips = sum(group.clips for group in result.synthetic.values())
        parts.append(f"{clips} synthetic clip{'' if clips == 1 else 's'}")
    if result.gate is not None:
        label = result.clearance.label  # None: a verdict may be issued
        each = []
        for provider, s in result.gate.items():
            numbers = f"CA {s.metrics.ca:.3f}, WA {s.metrics.wa:.3f}"
            verdict = "" if label is not None else ("PASS " if s.metrics.passed else "FAIL ")
            each.append(f"{provider} {verdict}({numbers})")
        parts.append(f"S1: {'' if label is None else label + ': '}{', '.join(each)}")
    return f"bakeoff: {'; '.join(parts)}; report written to {report_path}"


def _run(args: argparse.Namespace) -> int:
    try:
        require_input(args.synthetic, args.gate)
        register = clearance.read_register(args.register) if args.gate else None
        files = calibration.load(args.pack, args.calib)
        result = run(
            synthetic=args.synthetic,
            gate=args.gate,
            pack_toml=files.pack_toml,
            calib_json=files.calib_json,
            accent=args.accent,
            use_cache=not args.no_cache,
            register=register,
            allow_synthetic=args.allow_synthetic,
        )
        bakeoff_report.write(args.report, result, context=_context(args, files))
    except (
        BakeoffError,
        ManifestError,
        evaluate.EvalError,
        SynthError,
        metrics.MetricsError,
        provenance.ProvenanceError,
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
    p.add_argument(
        "--calib",
        help="calibration JSON (default: <pack stem>.calib.json beside the pack if it exists, "
        "as the tonekit CLI does, else tonekit's compiled-in default)",
    )
    p.add_argument("--accent", help="accent to grade against (default: the pack's base accent)")
    p.add_argument("--report", required=True, help="markdown report to write")
    p.add_argument(
        "--register",
        help="data register deciding which gate clip sources may back an S1 verdict "
        "(default: data-register.csv at the repository root)",
    )
    p.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="smoke run: grade synthetic gate clips and label the S1 section SMOKE (synthetic) "
        "instead of NOT A GATE; it never issues a PASS or FAIL",
    )
    p.add_argument(
        "--no-cache", action="store_true", help="neither read nor write the analysis cache"
    )
    p.set_defaults(func=_run)
