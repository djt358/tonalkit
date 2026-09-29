"""Grade every manifest clip with tonekit and collect one `Result` per clip.

Per clip: read the 16 kHz mono WAV, `tonekit_py.analyze` it (cached on disk), then
`tonekit_py.assess` the clip's intended reading against its distractors. A speaker's `register`
clips are graded first, chained so each is analysed with the register learnt from the ones before
it, and the final register is given to that speaker's other clips; a speaker with no register
clips is analysed cold, clip by clip.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import struct
import sys
import tomllib
import warnings
from dataclasses import dataclass, field
from functools import cache
from importlib import metadata
from pathlib import Path

import numpy as np
import tonekit_py
from scipy.io import wavfile

from . import manifest, metrics, report
from .ingest import TARGET_SR, to_float32
from .manifest import Clip, ManifestError, to_candidate_json

# harness/.cache/analysis, next to src/ (the directory is gitignored)
DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "analysis"

_REGISTER_SOURCES = {"ColdStart": "cold", "Given": "given"}


class EvalError(ValueError):
    """A clip could not be graded; the message names the clip."""


# A shape delta as (kind, amount): kind is a tonekit `DeltaKind` name such as "WiderRange";
# amount is in Chao units, or in ms for "TurnEarlier" and "TurnLater".
Delta = tuple[str, float]


@dataclass
class Syllable:
    """One syllable of the intended reading, from tonekit's `SyllableAssessment`."""

    expected: str
    heard: str | None
    p_correct: float
    distance: float | None
    measured: str  # "Full", "Partial" or "NotMeasured"
    deltas: list[Delta] = field(default_factory=list)


@dataclass
class Result:
    """How tonekit graded one clip."""

    id: str
    set: str
    pair: str | None
    label: str
    speaker: str
    overall: float | None  # None: no syllable was measured ("tone not checked")
    intended_rank: int  # 1: the intended reading beat every distractor
    margin_llr: float
    syllables: list[Syllable]
    register_source: str  # "cold" (estimated from this clip alone) or "given" (from register clips)
    issues: list[str] = field(default_factory=list)  # the analysis's signal issues, e.g. "LowSnr"


# ---- reading and caching ----------------------------------------------------------------------


def read_wav(path: Path, name: str) -> tuple[bytes, np.ndarray]:
    """The WAV file's bytes (for the cache key) and its 16 kHz mono samples as float32. `name`
    (a clip id) prefixes every `EvalError`."""
    try:
        data = path.read_bytes()
    except OSError as e:
        raise EvalError(f"{name}: cannot read {path}: {e.strerror or e}") from e
    try:
        with warnings.catch_warnings():
            # scipy only warns about a file cut short ("Reached EOF prematurely") and returns
            # fewer samples: that is an error here. Only a skipped unknown chunk is harmless.
            warnings.simplefilter("error", wavfile.WavFileWarning)
            warnings.filterwarnings(
                "ignore",
                message=r"Chunk \(non-data\) not understood",
                category=wavfile.WavFileWarning,
            )
            rate, samples = wavfile.read(io.BytesIO(data))
    except (ValueError, struct.error, wavfile.WavFileWarning) as e:
        raise EvalError(f"{name}: {path} is not a readable WAV file: {e}") from e
    if rate != TARGET_SR:
        raise EvalError(
            f"{name}: {path} is sampled at {rate} Hz, expected {TARGET_SR} Hz (run `tkh ingest`)"
        )
    if samples.ndim != 1:
        raise EvalError(f"{name}: {path} is not mono (run `tkh ingest`)")
    return data, to_float32(samples)


def _tonekit_py_version() -> str:
    try:
        return metadata.version("tonekit-py")
    except metadata.PackageNotFoundError:
        return "unknown"


@cache
def _tonekit_py_fingerprint() -> str:
    """The installed tonekit_py's version and a hash of its files. The version alone would not
    change when the Rust code does, so a rebuilt extension must also invalidate the cache."""
    h = hashlib.sha256()
    package = Path(tonekit_py.__file__).resolve().parent
    for f in sorted(p for p in package.iterdir() if p.suffix in {".so", ".pyd", ".dylib"}):
        h.update(f.name.encode())
        h.update(f.read_bytes())
    return f"{_tonekit_py_version()}+{h.hexdigest()}"


def _cache_key(wav: bytes, register_json: str | None) -> str:
    """sha256 over the WAV bytes, the register JSON and the tonekit_py version (each length-
    prefixed so the parts cannot run into each other)."""
    h = hashlib.sha256()
    for part in (wav, (register_json or "").encode(), _tonekit_py_fingerprint().encode()):
        h.update(len(part).to_bytes(8, "big"))
        h.update(part)
    return h.hexdigest()


def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _read_cached(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
        json.loads(text)
    except (OSError, ValueError):
        return None  # missing or corrupt: recompute
    return text


def _write_cached(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)  # atomic: a reader never sees a half-written entry


# ---- grading ----------------------------------------------------------------------------------


def base_accent(pack_toml: str) -> str:
    try:
        pack = tomllib.loads(pack_toml)
    except tomllib.TOMLDecodeError as e:
        raise EvalError(f"the pack is not valid TOML: {e}") from e
    accent = pack.get("pack", {}).get("base_accent")
    if not isinstance(accent, str):
        raise EvalError("the pack has no [pack] base_accent; pass an accent explicitly")
    return accent


def _measured_kind(measured: str | dict) -> str:
    """"Full", "Partial" or "NotMeasured" from tonekit's serde form (a string or a one-key map)."""
    return measured if isinstance(measured, str) else next(iter(measured))


def analyze_pcm(name: str, pcm: np.ndarray, register_json: str | None = None) -> str:
    """`tonekit_py.analyze` of 16 kHz samples; a tonekit failure is an `EvalError` naming `name`."""
    try:
        return tonekit_py.analyze(pcm, TARGET_SR, register_json)
    except ValueError as e:
        raise EvalError(f"{name}: {e}") from e


def grading_target(accent: str) -> dict:
    """The tonekit `GradingTarget` JSON object for `accent`: no imprint style."""
    return {"accent": accent, "style": None, "style_weight": 0.0}


@dataclass
class Grader:
    pack_toml: str
    calib_json: str | None
    accent: str
    root: Path
    cache_dir: Path | None  # None: no cache

    def analysis(self, clip: Clip, register_json: str | None) -> str:
        wav, pcm = read_wav(self.root / clip.path, clip.id)
        entry = None
        if self.cache_dir is not None:
            entry = self.cache_dir / f"{_cache_key(wav, register_json)}.json"
            if (text := _read_cached(entry)) is not None:
                return text
        text = analyze_pcm(clip.id, pcm, register_json)
        if entry is not None:
            _write_cached(entry, text)
        return text

    def grade(self, clip: Clip, register_json: str | None) -> tuple[Result, dict]:
        """The clip's `Result` and the raw assessment (whose `register_update` chains registers)."""
        return self.assess(clip, self.analysis(clip, register_json))

    def grade_pcm(
        self, clip: Clip, pcm: np.ndarray, register_json: str | None = None
    ) -> tuple[Result, dict]:
        """Like `grade`, for samples in memory: `clip.path` is not read and nothing is cached."""
        return self.assess(clip, analyze_pcm(clip.id, pcm, register_json))

    def assess(self, clip: Clip, analysis_json: str) -> tuple[Result, dict]:
        request = {
            "grading": grading_target(self.accent),
            "intended": json.loads(to_candidate_json(clip.intended)),
            "distractors": [json.loads(to_candidate_json(d)) for d in clip.distractors],
            "external": [],
            "compare_accents": [],
        }
        try:
            assessed = tonekit_py.assess(
                analysis_json, self.pack_toml, self.calib_json, json.dumps(request)
            )
        except ValueError as e:
            raise EvalError(f"{clip.id}: {e}") from e
        assessment = json.loads(assessed)
        analysis = json.loads(analysis_json)
        source = analysis["register_source"]
        result = Result(
            id=clip.id,
            set=clip.set,
            pair=clip.pair,
            label=clip.label,
            speaker=clip.speaker,
            overall=assessment["overall"],
            intended_rank=assessment["intended_rank"],
            margin_llr=assessment["margin_llr"],
            syllables=[
                Syllable(
                    expected=s["expected"],
                    heard=s["heard"],
                    p_correct=s["p_correct"],
                    distance=s["distance"],
                    measured=_measured_kind(s["measured"]),
                    deltas=[(d["kind"], d["amount"]) for d in s["deltas"]],
                )
                for s in assessment["syllables"]
            ],
            register_source=_REGISTER_SOURCES.get(source, source.lower()),
            issues=list(analysis["issues"]),
        )
        return result, assessment


def _chain_registers(
    clips: list[Clip], grader: Grader
) -> tuple[dict[str, str | None], dict[str, Result]]:
    """Each speaker's register after their `register` clips, and those clips' results.

    A speaker's register clips are graded in manifest order, each analysed with the register
    learnt from the ones before it; a clip that measured nothing teaches nothing. A speaker with
    no register clips maps to None."""
    by_id: dict[str, Result] = {}
    registers: dict[str, str | None] = {}
    for speaker in dict.fromkeys(c.speaker for c in clips):
        register_json: str | None = None
        for clip in (c for c in clips if c.speaker == speaker and c.set == "register"):
            result, assessment = grader.grade(clip, register_json)
            by_id[clip.id] = result
            update = assessment["register_update"]
            if update["n_syllables"] > 0:  # nothing measured: there is nothing to learn from
                register_json = _canonical(update)
        registers[speaker] = register_json
    return registers, by_id


def speaker_registers(clips: list[Clip], grader: Grader) -> dict[str, str | None]:
    """Each speaker's register as tonekit `Register` JSON (None if they have no register clips or
    none measured anything): what `run` analyses that speaker's other clips with."""
    return _chain_registers(clips, grader)[0]


def run(
    clips: list[Clip],
    pack_toml: str,
    calib_json: str | None,
    accent: str | None,
    *,
    root: str | Path = ".",
    cache_dir: str | Path | None = None,
    use_cache: bool = True,
) -> list[Result]:
    """Grade `clips`, returning one `Result` per clip in the same order.

    `accent` defaults to the pack's `base_accent`. Each clip's `path` is relative to `root`.
    Analyses are cached under `cache_dir` (default `DEFAULT_CACHE_DIR`) unless `use_cache` is
    false. Raises `EvalError` (naming the clip) if a clip cannot be read or graded.
    """
    seen: set[str] = set()
    for clip in clips:
        if clip.id in seen:
            raise EvalError(f"duplicate clip id {clip.id!r}")
        seen.add(clip.id)

    grader = Grader(
        pack_toml=pack_toml,
        calib_json=calib_json,
        accent=accent or base_accent(pack_toml),
        root=Path(root),
        cache_dir=Path(cache_dir or DEFAULT_CACHE_DIR) if use_cache else None,
    )

    registers, by_id = _chain_registers(clips, grader)
    for clip in clips:
        if clip.id not in by_id:
            by_id[clip.id] = grader.grade(clip, registers[clip.speaker])[0]
    return [by_id[c.id] for c in clips]


# ---- tkh eval ---------------------------------------------------------------------------------


def _run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    try:
        clips = manifest.load(manifest_path)
        pack_toml = Path(args.pack).read_text(encoding="utf-8")
        calib_json = Path(args.calib).read_text(encoding="utf-8") if args.calib else None
        results = run(
            clips,
            pack_toml,
            calib_json,
            args.accent,
            root=manifest_path.parent,  # clip paths are relative to the manifest's directory
            use_cache=not args.no_cache,
        )
        gate = metrics.loo_gate(results)
        theta = gate.median_threshold
        sets = list(dict.fromkeys(c.set for c in clips))
        per_set = {name: sum(c.set == name for c in clips) for name in sets}
        report.write(
            args.report,
            gate,
            metrics.candidate_id_accuracy(results),
            metrics.count_robustness(results, theta),
            metrics.failures(results, gate, theta),
            n_minimal=per_set.get("diag_minimal", 0),
            n_count=per_set.get("diag_count", 0),
            context={
                "manifest": str(args.manifest),
                "pack": str(args.pack),
                "calibration": str(args.calib) if args.calib else "the pack's own",
                "accent": args.accent or "the pack's base accent",
                "clips": ", ".join(f"{name} {n}" for name, n in per_set.items()),
                "tonekit-py": _tonekit_py_version(),
            },
        )
    except (ManifestError, EvalError, metrics.MetricsError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    verdict = "PASS" if gate.passed else "FAIL"
    print(f"S1: {verdict} (CA {gate.ca:.3f}, WA {gate.wa:.3f}); report written to {args.report}")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "eval", help="grade the corpus, compute the leave-one-pair-out gate and write a report"
    )
    p.add_argument("--manifest", required=True, help="corpus manifest (JSONL)")
    p.add_argument("--pack", required=True, help="language pack TOML (e.g. packs/cmn/cmn.toml)")
    p.add_argument("--calib", help="calibration JSON (default: the pack's own)")
    p.add_argument("--accent", help="accent to grade against (default: the pack's base accent)")
    p.add_argument("--report", required=True, help="markdown report to write")
    p.add_argument(
        "--no-cache", action="store_true", help="neither read nor write the analysis cache"
    )
    p.set_defaults(func=_run)
