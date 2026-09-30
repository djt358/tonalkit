"""Controlled resynthesis (spec §9): resynthesise a real, correct recording with its f0 replaced by
a perturbed target contour. The timbre stays real, and the tone and f0 ground truth are exact.

`perturb` makes one perturbed clip from a prepared `source.Source`; `tkh synth` samples many.
Synthetic audio is for tests and diagnostics, never for fitting shipped calibration: every row's
`source` is `synthetic-world`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from . import corpus, evaluate, families, source, world
from .corpus import Made
from .family import SynthError
from .manifest import Clip, ManifestError
from .source import Source

PEAK = 0.99  # tonekit flags a clip with more than 1% of samples at or above this


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
    gives the same audio.

    If the result would peak above `PEAK` it is turned down to it; the row's
    `synthetic["limiter_gain"]` is that gain (1.0 when the limiter did not act)."""
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
    gain = PEAK / peak if peak > PEAK else 1.0
    if gain < 1.0:
        y = y * np.float32(gain)

    truth = [None if h == 0.0 else float(h) for h in hz]
    return y, truth, _row(src, fam, p, seed, gain)


def _row(src: Source, fam: families.Family, p: dict, seed: int, limiter_gain: float) -> Clip:
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
        synthetic={
            "from": src.clip.id,
            "family": fam.name,
            "params": p,
            "seed": seed,
            "limiter_gain": limiter_gain,
        },
    )


# ---- tkh synth --------------------------------------------------------------------------------


def plural(n: int, noun: str) -> str:
    """`n` `noun`(s), for the summary lines."""
    return f"{n} {noun}{'' if n == 1 else 's'}"


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
    skipped: list[str] = []
    n_sources = 0
    try:
        if args.per_clip < 1:
            raise SynthError(f"--per-clip must be at least 1, not {args.per_clip}")
        pool = families.searched(("tone_error", "graded", "correct"))
        bounds = families.resolve_pool_bounds(pool, None)
        rng = np.random.default_rng(args.seed)
        made = []
        # one source at a time: its analysis is dropped once its perturbations are made
        for src in source.load_sources(
            args.manifest, args.pack, args.calib, args.accent, skipped=skipped
        ):
            n_sources += 1
            for _ in range(args.per_clip):
                fam, params = families.draw(src.voice, rng, pool, bounds)
                made.append(perturb(src, fam.name, params, int(rng.integers(2**31))))
        corpus.write_corpus(args.out, made)
    except (ManifestError, evaluate.EvalError, SynthError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(
        f"synthesised {plural(len(made), 'clip')} from {plural(n_sources, 'source')} "
        f"({len(skipped)} skipped); written to {args.out}"
    )
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "synth", help="WORLD-resynthesise perturbed variants of the correct clips, with f0 truth"
    )
    add_source_args(p)
    p.add_argument("--per-clip", type=int, required=True, help="perturbed clips to make per source")
    p.set_defaults(func=_run)
