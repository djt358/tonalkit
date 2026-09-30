"""Source clips for the synthetic corpus: a correct recording analysed once with WORLD and
tonekit, ready to be perturbed many times (`prepare`), and the loader that prepares every correct
clip of a manifest with its speaker's register, one at a time (`load_sources`).

A syllable's extent is its voiced core (`voiced_core`): within the span tonekit decoded for it, the
longest run of frames that WORLD and tonekit's pitch tracker both call voiced, so a stray voiced
frame at the edge of a span does not stretch it."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tonekit_py

from . import evaluate, manifest, world
from .family import SynthError
from .manifest import Clip
from .voice import PackTones, Voice

MIN_VOICED_FRAMES = 5  # a syllable needs this many voiced frames to be redrawn (50 ms)
MAX_GAP_FRAMES = 2  # unvoiced frames a voiced core tolerates inside itself (20 ms)
MIN_REGISTER_ST = 4.0  # tonekit's minimum register width, expanded symmetrically


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
    register_json: str | None  # the speaker's register from their register clips; None: cold


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


def voiced_core(voiced: np.ndarray, max_gap: int = MAX_GAP_FRAMES) -> tuple[int, int] | None:
    """The voiced core [start, end) of a syllable's frames: the run with the most voiced frames,
    where voiced frames at most `max_gap` unvoiced frames apart belong to the same run. None if
    that run has fewer than `MIN_VOICED_FRAMES` voiced frames. A stray voiced frame at the edge of
    the span (noise, a neighbour's tail) is a run of its own, so it never stretches the core."""
    frames = np.flatnonzero(voiced)
    if len(frames) == 0:
        return None
    runs = np.split(frames, np.flatnonzero(np.diff(frames) > max_gap + 1) + 1)
    run = max(runs, key=len)  # the first, on a tie
    if len(run) < MIN_VOICED_FRAMES:
        return None
    return int(run[0]), int(run[-1]) + 1


def _extents(
    clip: Clip,
    pcm: np.ndarray,
    world_voiced: np.ndarray,
    pack_toml: str,
    calib_json: str | None,
    accent: str,
    register_json: str | None,
) -> list[tuple[int, int] | None]:
    """The voiced core [start, end) of each intended syllable, or None if it has none to redraw.

    tonekit decodes the clip against its own intended reading (analysed with the speaker's
    register, so the same way the grader will see it) to say where each syllable is. A decoded span
    can include silence or a neighbour's tail, and WORLD calls some noise voiced, so the core is
    the longest run (`voiced_core`) of frames that both WORLD and tonekit's pitch tracker call
    voiced within the span."""
    analysis_json = evaluate.analyze_pcm(clip.id, pcm, register_json)
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
        core = voiced_core(voiced[start:end])
        extents.append(None if core is None else (start + core[0], start + core[1]))
    return extents


def prepare(
    clip: Clip,
    *,
    root: str | Path,
    pack_toml: str,
    calib_json: str | None = None,
    accent: str | None = None,
    register_json: str | None = None,
) -> Source:
    """Read `clip` (its `path` is relative to `root`) and do the once-per-clip analysis.

    `register_json` is the speaker's register (see `evaluate.speaker_registers`); the clip's spans
    are decoded with it, and `adversary.search` grades the clip's perturbations with it.

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
    extents = (
        _extents(clip, pcm, voiced, pack_toml, calib_json, accent, register_json)
        if voiced.any()
        else []
    )
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
    return Source(clip, pcm, analysed, voice, pack_toml, calib_json, accent, register_json)


def load_sources(
    manifest_path: str | Path,
    pack: str | Path,
    calib: str | Path | None,
    accent: str | None,
    *,
    skipped: list[str] | None = None,
) -> Iterator[Source]:
    """`prepare` every non-synthetic clip labelled `correct` in the manifest, one at a time (a
    generator: a source is analysed when the caller asks for it, and can be dropped once used),
    each with its speaker's register (chained from their `register` clips exactly as `tkh eval`
    does; cold if they have none).

    A clip with nothing to perturb is skipped with a warning on stderr; its message is appended to
    `skipped`, if given, so the caller can report how many. It is an error (`SynthError`, raised
    when the generator is exhausted) if no clip could be perturbed."""
    manifest_path = Path(manifest_path)
    clips = manifest.load(manifest_path)
    pack_toml = Path(pack).read_text(encoding="utf-8")
    calib_json = Path(calib).read_text(encoding="utf-8") if calib else None
    grader = evaluate.Grader(
        pack_toml,
        calib_json,
        accent or evaluate.base_accent(pack_toml),
        root=manifest_path.parent,
        cache_dir=None,
    )
    registers = evaluate.speaker_registers(clips, grader)
    found = 0
    for clip in clips:
        if clip.label != "correct" or clip.set == "synthetic":
            continue
        try:
            src = prepare(
                clip,
                root=manifest_path.parent,
                pack_toml=pack_toml,
                calib_json=calib_json,
                accent=accent,
                register_json=registers[clip.speaker],
            )
        except SynthError as e:
            print(f"warning: skipping {e}", file=sys.stderr)
            if skipped is not None:
                skipped.append(str(e))
            continue
        found += 1
        yield src
    if not found:
        raise SynthError(f"{manifest_path}: no clip labelled 'correct' can be perturbed")
