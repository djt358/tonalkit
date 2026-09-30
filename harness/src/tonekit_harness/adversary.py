"""Random-search adversary (spec §9, P0): perturb real clips at random within the spec's bounds and
keep the cases where tonekit is wrong.

A trial perturbs one source with a random tone-error or nuisance family (the class first, each
equally likely, then a family within it) and asks tonekit to grade the result against the source's
intended reading, the way `tkh eval` grades a clip: analysed with the speaker's register (from
their register clips, if the manifest has any; cold otherwise) and scored by the same `assess`.
That keeps θ, typically fitted on `tkh eval` scores, comparable.

The overall score is accepted at or above θ (no score, "tone not checked", is a rejection). A find
is a false accept (a tone error tonekit accepts) or a false reject (a nuisance-only clip, which a
listener would accept, that tonekit rejects). Graded families have no binary truth, so they are not
searched. Finds sit near the perceptual boundary, where the label itself is uncertain: they are
marked `needs_listen` and never become fixtures or move a threshold before DJ has listened to
them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np

from . import corpus, evaluate, families, source, synth
from .family import SynthError
from .manifest import Clip, ManifestError
from .source import Source

BoundOverrides = Mapping[str, Mapping[str, tuple[float, float]]]


class Finds(list):
    """The finds, most damning first, with how the search went. The list holds the finds' manifest
    `Clip`s: false accepts by score descending, then false rejects by score ascending (a clip with
    no score first), ties by id."""

    def __init__(self, finds: Sequence[Clip], trials: int, failed: int):
        super().__init__(finds)
        self.trials = trials  # trials run, including failed ones
        self.failed = failed  # trials in which tonekit raised (skipped, not finds)

    @property
    def false_accepts(self) -> int:
        return sum(c.label == "tone_error" for c in self)

    @property
    def false_rejects(self) -> int:
        return sum(c.label == "correct" for c in self)


def search(
    sources: Sequence[Source],
    n_trials: int,
    bounds: BoundOverrides | None,
    seed: int,
    theta: float,
    *,
    out_dir: str | Path,
    noise_wav: str | None = None,
) -> Finds:
    """Run `n_trials` random trials over `sources` and write the finds to `out_dir` (WAVs under
    `wav/`, `manifest.jsonl`, `truth.jsonl`). `out_dir` must be empty or not exist yet
    (`SynthError` otherwise): stale files would otherwise mix with the new manifest. The manifest
    and truth are written even if the search is interrupted, listing the finds made so far.

    `bounds` maps a family to `{parameter: (lo, hi)}` to narrow the spec's bounds (for a signed
    parameter, a magnitude); anything outside the spec's is a `SynthError`. The search is
    deterministic in `seed`. Each trial picks the class (tone error or nuisance) first, each
    equally likely, then a family within it (see `families.draw`). `noise_wav`, a 16 kHz mono
    recording, is what the `noise` family adds instead of pink noise.

    Each trial is graded with its source's register (`Source.register_json`: the speaker's, as
    `tkh eval` grades that speaker's clips), and each find records whether that register was
    `given` or `cold`. A trial in which tonekit raises is counted as failed and skipped."""
    if not sources:
        raise SynthError("no sources to search")
    if n_trials < 0:
        raise SynthError(f"n_trials must not be negative, not {n_trials}")
    pool = families.searched(("tone_error", "correct"))
    resolved = families.resolve_pool_bounds(pool, bounds)
    synth.check_noise_wav(noise_wav)
    paths = None if noise_wav is None else {"noise_wav": noise_wav}
    corpus.require_empty(out_dir)
    rng = np.random.default_rng(seed)
    graders: dict[tuple, evaluate.Grader] = {}

    found: list[tuple[Clip, list, float | None]] = []
    failed = 0
    try:
        for _ in range(n_trials):
            src = sources[int(rng.integers(len(sources)))]
            fam, params = families.draw(src.voice, rng, pool, resolved, paths)
            audio, truth, clip = synth.perturb(src, fam.name, params, int(rng.integers(2**31)))
            key = (src.pack_toml, src.calib_json, src.accent)
            if key not in graders:
                graders[key] = evaluate.Grader(*key, root=Path("."), cache_dir=None)
            try:
                result, _ = graders[key].grade_pcm(clip, audio, src.register_json)
            except evaluate.EvalError:
                failed += 1
                continue
            score = result.overall
            accepted = score is not None and score >= theta
            if fam.label == "tone_error" and accepted:
                kind = "false_accept"
            elif fam.label == "correct" and not accepted:
                kind = "false_reject"
            else:
                continue
            row = clip.model_copy(
                update={
                    "needs_listen": True,
                    "synthetic": {
                        **(clip.synthetic or {}),
                        "adversary": {
                            "kind": kind,
                            "score": score,
                            "theta": theta,
                            "register": result.register_source,
                        },
                    },
                }
            )
            corpus.write_wav(out_dir, row, audio)
            found.append((row, truth, score))
    finally:
        # also when interrupted: every WAV written above gets its row
        accepts = sorted((f for f in found if f[0].label == "tone_error"), key=_accept_order)
        rejects = sorted((f for f in found if f[0].label == "correct"), key=_reject_order)
        ordered = accepts + rejects
        corpus.write_index(out_dir, [c for c, _, _ in ordered], [t for _, t, _ in ordered])
    return Finds([c for c, _, _ in ordered], n_trials, failed)


def _accept_order(find: tuple[Clip, list, float | None]) -> tuple[float, str]:
    return -find[2], find[0].id  # type: ignore[operator]  # accepted, so scored


def _reject_order(find: tuple[Clip, list, float | None]) -> tuple[float, str]:
    return (-1.0 if find[2] is None else find[2]), find[0].id  # unscored before any score


# ---- tkh adversary ----------------------------------------------------------------------------


def _run(args: argparse.Namespace) -> int:
    skipped: list[str] = []
    try:
        corpus.require_empty(args.out)
        synth.check_noise_wav(args.noise_wav)
        sources = list(
            source.load_sources(args.manifest, args.pack, args.calib, args.accent, skipped=skipped)
        )
        finds = search(
            sources,
            args.trials,
            None,
            args.seed,
            args.theta,
            out_dir=args.out,
            noise_wav=args.noise_wav,
        )
    except (ManifestError, evaluate.EvalError, SynthError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(
        f"adversary: {finds.trials} trials ({finds.failed} failed), "
        f"{finds.false_accepts} false accepts, {finds.false_rejects} false rejects; "
        f"{synth.plural(len(sources), 'source')} ({len(skipped)} skipped); written to {args.out}"
    )
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "adversary",
        help="random search for false accepts and false rejects over perturbed clips",
    )
    synth.add_source_args(p)
    p.add_argument("--trials", type=int, required=True, help="random trials to run")
    p.add_argument("--theta", type=float, required=True, help="accept a clip scoring at least this")
    p.set_defaults(func=_run)
