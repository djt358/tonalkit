"""Controlled resynthesis (spec §9): analyse a real, correct recording once with WORLD, then
resynthesise it with its f0 replaced by a perturbed target contour. The timbre stays real, and the
tone and f0 ground truth are exact.

`prepare` does the per-clip work (WORLD analysis, tonekit's syllable spans); `perturb` makes one
perturbed clip from it; `tkh synth` samples many. Synthetic audio is for tests and diagnostics,
never for fitting shipped calibration: every row's `source` is `synthetic-world`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tonekit_py
from scipy.io import wavfile

from . import evaluate, families, manifest, world
from .families import PackTones, SynthError, Voice
from .ingest import TARGET_SR
from .manifest import Clip, ManifestError

MIN_VOICED_FRAMES = 5  # a syllable needs this many voiced frames to be redrawn (50 ms)
MIN_REGISTER_ST = 4.0  # tonekit's minimum register width, expanded symmetrically
PEAK = 0.99  # tonekit flags a clip with more than 1% of samples at or above this

# One perturbed clip: its samples, the f0 truth per 10 ms frame (None where unvoiced), its row.
Made = tuple[np.ndarray, list[float | None], Clip]


@dataclass(frozen=True)
class Source:
    """A correct clip, analysed once and ready to perturb many times."""

    clip: Clip
    pcm: np.ndarray  # float32, 16 kHz
    world: world.World
    voice: Voice  # syllable extents, f0 in semitones, register (what the families see)
    pack_toml: str
    calib_json: str | None
    accent: str


# ---- analysis ---------------------------------------------------------------------------------


def _semitones(hz: np.ndarray) -> np.ndarray:
    """Semitones re 55 Hz, NaN where unvoiced (hz == 0)."""
    voiced = hz > 0
    return np.where(voiced, 12.0 * np.log2(np.where(voiced, hz, 55.0) / 55.0), np.nan)


def register_bounds(voiced_st: np.ndarray) -> tuple[float, float]:
    """The speaker's register as (floor, ceil) semitones: p5 and p95 of the voiced semitones, at
    least `MIN_REGISTER_ST` wide (expanded symmetrically), Chao 1 and Chao 5."""
    floor, ceil = (float(x) for x in np.percentile(voiced_st, [5, 95]))
    if ceil - floor < MIN_REGISTER_ST:
        mid = (floor + ceil) / 2.0
        floor, ceil = mid - MIN_REGISTER_ST / 2.0, mid + MIN_REGISTER_ST / 2.0
    return floor, ceil


def _extents(
    clip: Clip, pcm: np.ndarray, world_voiced: np.ndarray, pack_toml: str, calib_json, accent
) -> list[tuple[int, int] | None]:
    """The voiced core [start, end) of each intended syllable, or None if it has none to redraw.

    tonekit decodes the clip against its own intended reading (analysed cold, so the same way the
    grader will see it) to say where each syllable is. A decoded span can include silence or a
    neighbour's tail, and WORLD calls some noise voiced, so the core is the run from the first to
    the last frame that both WORLD and tonekit's pitch tracker call voiced within the span."""
    analysis_json = evaluate.analyze_pcm(clip.id, pcm)
    analysis = json.loads(analysis_json)
    voiced = world_voiced & np.array([f["hz"] is not None for f in analysis["f0"]["frames"]])
    intended = json.loads(manifest.to_candidate_json(clip.intended))
    try:
        decoded = tonekit_py.decode(
            analysis_json,
            pack_toml,
            calib_json,
            json.dumps(evaluate.grading_target(accent)),
            json.dumps([intended]),
        )
    except ValueError as e:
        raise evaluate.EvalError(f"{clip.id}: {e}") from e
    syllables = json.loads(decoded)["candidates"][0]["syllables"]
    if len(syllables) != len(clip.intended.tones):
        raise SynthError(
            f"{clip.id}: tonekit found {len(syllables)} syllables, "
            f"not the intended {len(clip.intended.tones)}"
        )
    extents: list[tuple[int, int] | None] = []
    for syllable in syllables:
        start, end = syllable["span"]["start_frame"], syllable["span"]["end_frame"]
        frames = np.flatnonzero(voiced[start:end])
        if len(frames) < MIN_VOICED_FRAMES:
            extents.append(None)
        else:
            extents.append((start + int(frames[0]), start + int(frames[-1]) + 1))
    return extents


def prepare(
    clip: Clip,
    *,
    root: str | Path,
    pack_toml: str,
    calib_json: str | None = None,
    accent: str | None = None,
) -> Source:
    """Read `clip` (its `path` is relative to `root`) and do the once-per-clip analysis.

    Only correct, non-synthetic clips can be perturbed: the label of a perturbed clip comes from
    the family, and would be wrong for a clip that is already wrong or already synthetic."""
    if clip.set == "synthetic":
        raise SynthError(f"{clip.id}: a synthetic clip cannot be perturbed again")
    if clip.label != "correct":
        raise SynthError(
            f"{clip.id}: labelled {clip.label!r}; only clips labelled 'correct' can be perturbed"
        )
    if Path(clip.id).name != clip.id or clip.id in {"", ".", ".."}:
        raise SynthError(f"{clip.id!r}: the id must be usable as a file name")
    pack = PackTones.parse(pack_toml)
    unknown = [t for t in clip.intended.tones if t not in pack.chao]
    if unknown:
        raise SynthError(f"{clip.id}: tone {unknown[0]!r} is not in the pack")
    accent = accent or evaluate.base_accent(pack_toml)

    _, pcm = evaluate.read_wav(Path(root) / clip.path, clip.id)
    analysed = world.analyse(pcm)
    voiced = analysed.f0 > 0
    extents = _extents(clip, pcm, voiced, pack_toml, calib_json, accent) if voiced.any() else []
    if not any(extents):
        raise SynthError(
            f"{clip.id}: no syllable with at least {MIN_VOICED_FRAMES} voiced frames to perturb"
        )

    st = _semitones(analysed.f0)
    floor, ceil = register_bounds(st[voiced])
    voice = Voice(
        tones=tuple(clip.intended.tones),
        extents=tuple(extents),
        st=st,
        floor=floor,
        ceil=ceil,
        pack=pack,
    )
    return Source(clip, pcm, analysed, voice, pack_toml, calib_json, accent)


# ---- perturbation -----------------------------------------------------------------------------


def _resample_f0(st: np.ndarray, pos: np.ndarray) -> np.ndarray:
    """`st` (NaN where unvoiced) at fractional frame positions `pos`: a frame is voiced if its
    nearest source frame is, and takes the semitones interpolated between voiced frames."""
    voiced = ~np.isnan(st)
    at = np.flatnonzero(voiced)
    keep = voiced[np.rint(pos).astype(int)]
    out = np.full(len(pos), np.nan)
    out[keep] = np.interp(pos[keep], at, st[at])
    return out


def _resample_rows(a: np.ndarray, pos: np.ndarray) -> np.ndarray:
    """The rows of `a` at fractional positions `pos`, linearly interpolated."""
    i0 = np.floor(pos).astype(int)
    i1 = np.minimum(i0 + 1, len(a) - 1)
    frac = (pos - i0)[:, None]
    return a[i0] * (1.0 - frac) + a[i1] * frac


def _voiced_samples(voiced_frames: np.ndarray, n_samples: int) -> np.ndarray:
    """Which samples lie in a voiced frame: frame i covers samples i * HOP +- HOP / 2."""
    frame = np.minimum((np.arange(n_samples) + world.HOP // 2) // world.HOP, len(voiced_frames) - 1)
    return voiced_frames[frame]


def _noise_bed(params: dict) -> np.ndarray | None:
    path = params.get("noise_wav")
    if path is None:
        return None
    try:
        return evaluate.read_wav(Path(path), "noise_wav")[1]
    except evaluate.EvalError as e:
        raise SynthError(f"noise: {e}") from e


def perturb(src: Source, family: str, params: dict, seed: int) -> Made:
    """One perturbed clip of `src`: the audio (16 kHz float32), the ground-truth f0 per 10 ms
    frame (`len(audio) // 160 + 1` entries, exactly what WORLD was given, None where 0) and the
    manifest row. The row's `path` is `wav/<id>.wav`, relative to wherever the corpus is written.

    `params` are the family's (see `families`); out-of-bounds values are a `SynthError`. All
    families, `identity` included, pass through WORLD, so they are comparable. The same `seed`
    gives the same audio."""
    fam = families.get(family)
    p = fam.validate(src.voice, params)
    rng = np.random.default_rng(seed)

    st = fam.contour(src.voice, p)
    speed = fam.speed(p)  # above 1: faster, so shorter
    n_samples = round(len(src.pcm) / speed)
    pos = np.minimum(np.arange(world.n_frames(n_samples)) * speed, len(src.world.f0) - 1)
    st = _resample_f0(st, pos)
    # WORLD is only defined over its own search range, so a large shift or a wide onset is
    # clipped to it (that also keeps the ground truth honest: it is what was synthesised).
    hz = np.clip(55.0 * 2.0 ** (np.nan_to_num(st) / 12.0), world.F0_FLOOR, world.F0_CEIL)
    hz[np.isnan(st)] = 0.0
    resynth = world.World(
        f0=hz, sp=_resample_rows(src.world.sp, pos), ap=_resample_rows(src.world.ap, pos)
    )

    y = world.synthesise(resynth, n_samples)
    y = fam.audio(y, _voiced_samples(hz > 0, n_samples), p, rng, _noise_bed(p))
    peak = float(np.abs(y).max())
    if peak > PEAK:
        y = y * np.float32(PEAK / peak)

    truth = [None if h == 0.0 else float(h) for h in hz]
    return y, truth, _row(src, fam, p, seed)


def _row(src: Source, fam: families.Family, p: dict, seed: int) -> Clip:
    key = json.dumps({"params": p, "seed": seed}, sort_keys=True, separators=(",", ":"))
    cid = f"{src.clip.id}~{fam.name}~{hashlib.sha256(key.encode()).hexdigest()[:8]}"
    produced = fam.produced(src.voice, p)
    noise = fam.condition_noise(p)
    condition = src.clip.condition
    if noise is not None:
        condition = condition.model_copy(update={"noise": noise})
    return Clip(
        id=cid,
        path=f"wav/{cid}.wav",
        speaker=src.clip.speaker,
        set="synthetic",
        pair=None,
        label=fam.label,  # type: ignore[arg-type]
        intended=src.clip.intended.model_copy(deep=True),
        distractors=[d.model_copy(deep=True) for d in src.clip.distractors],
        produced_tones=src.clip.produced_tones if produced is None else produced,
        condition=condition,
        source="synthetic-world",
        synthetic={"from": src.clip.id, "family": fam.name, "params": p, "seed": seed},
    )


# ---- writing ----------------------------------------------------------------------------------


def write_wav(out_dir: str | Path, clip: Clip, audio: np.ndarray) -> None:
    """Write `audio` to `clip.path` under `out_dir` as a 16 kHz mono float32 WAV."""
    path = Path(out_dir) / clip.path
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(path, TARGET_SR, np.asarray(audio, dtype=np.float32))


def write_index(out_dir: str | Path, clips: Sequence[Clip], truths: Sequence[list[float | None]]):
    """Write `manifest.jsonl` and `truth.jsonl` (`{"id", "f0_hz"}` per clip, null if unvoiced)."""
    out = Path(out_dir)
    manifest.write(out / "manifest.jsonl", list(clips))
    lines = (
        json.dumps({"id": c.id, "f0_hz": f0}) + "\n" for c, f0 in zip(clips, truths, strict=True)
    )
    (out / "truth.jsonl").write_text("".join(lines), encoding="utf-8")


def write_corpus(out_dir: str | Path, made: Sequence[Made]) -> None:
    """Write perturbed clips (WAVs under `wav/`, the manifest and the truth) to `out_dir`."""
    for audio, _, clip in made:
        write_wav(out_dir, clip, audio)
    write_index(out_dir, [c for _, _, c in made], [f0 for _, f0, _ in made])


# ---- tkh synth --------------------------------------------------------------------------------


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def load_sources(
    manifest_path: str | Path, pack: str | Path, calib: str | Path | None, accent: str | None
) -> list[Source]:
    """`prepare` every non-synthetic clip labelled `correct` in the manifest. A clip with nothing
    to perturb is skipped with a warning; it is an error if none can be perturbed."""
    manifest_path = Path(manifest_path)
    clips = manifest.load(manifest_path)
    pack_toml = Path(pack).read_text(encoding="utf-8")
    calib_json = Path(calib).read_text(encoding="utf-8") if calib else None
    candidates = [c for c in clips if c.label == "correct" and c.set != "synthetic"]
    sources = []
    for clip in candidates:
        try:
            sources.append(
                prepare(
                    clip,
                    root=manifest_path.parent,
                    pack_toml=pack_toml,
                    calib_json=calib_json,
                    accent=accent,
                )
            )
        except SynthError as e:
            print(f"warning: skipping {e}", file=sys.stderr)
    if not sources:
        raise SynthError(f"{manifest_path}: no clip labelled 'correct' can be perturbed")
    return sources


def add_source_args(p: argparse.ArgumentParser) -> None:
    """The arguments `tkh synth` and `tkh adversary` share."""
    p.add_argument(
        "--manifest", required=True, help="corpus manifest (JSONL); its correct clips are sources"
    )
    p.add_argument("--pack", required=True, help="language pack TOML (e.g. packs/cmn/cmn.toml)")
    p.add_argument("--calib", help="calibration JSON (default: the pack's own)")
    p.add_argument("--accent", help="accent to grade against (default: the pack's base accent)")
    p.add_argument("--out", required=True, help="directory for the WAVs, manifest and truth")
    p.add_argument("--seed", type=int, default=0, help="random seed (default 0)")


def _run(args: argparse.Namespace) -> int:
    try:
        if args.per_clip < 1:
            raise SynthError(f"--per-clip must be at least 1, not {args.per_clip}")
        sources = load_sources(args.manifest, args.pack, args.calib, args.accent)
        pool = families.searched(("tone_error", "graded", "correct"))
        bounds = families.resolve_pool_bounds(pool, None)
        rng = np.random.default_rng(args.seed)
        made = []
        for src in sources:
            for _ in range(args.per_clip):
                fam, params = families.draw(src.voice, rng, pool, bounds)
                made.append(perturb(src, fam.name, params, int(rng.integers(2**31))))
        write_corpus(args.out, made)
    except (ManifestError, evaluate.EvalError, SynthError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(
        f"synthesised {_plural(len(made), 'clip')} from {_plural(len(sources), 'source')}; "
        f"written to {args.out}"
    )
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "synth", help="WORLD-resynthesise perturbed variants of the correct clips, with f0 truth"
    )
    add_source_args(p)
    p.add_argument("--per-clip", type=int, required=True, help="perturbed clips to make per source")
    p.set_defaults(func=_run)
