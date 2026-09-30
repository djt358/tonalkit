"""Synthetic corpora for the harness tests: a tiny harmonic voice that speaks Chao-knot tones.

The voice is a sum of eight harmonics whose f0 follows the tone's Chao knots (equally spaced in
time, linear in Chao value) between a 100 Hz floor and a 200 Hz ceiling. Chao value c maps to
100 * 2**((c - 1) / 4) Hz, exactly tonekit's `1 + 4 * (st - floor_st) / (ceil_st - floor_st)`.
By default syllables are 250 ms (the neutral tone half that) with 150 ms gaps, and 300 ms of
near-silence (a fixed low noise floor) on each side, so the segmenter finds one nucleus per
syllable. Everything is deterministic.

Synthetic audio is for testing the harness only; it is never used to fit shipped calibration.
The clips are registered as `synthetic-world` (deny in data-register.csv), so `tkh eval` calls a
run over them "NOT A GATE" or, with `--allow-synthetic`, "SMOKE"; pass `source="dj-corpus"` to
stand in for a recording when a test is about the PASS/FAIL headline itself.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.io import wavfile

from tonekit_harness.manifest import Candidate, Clip, Condition

RATE = 16_000
FLOOR_HZ = 100.0
CEIL_HZ = 200.0
SYLLABLE_S = 0.25
GAP_S = 0.15
EDGE_S = 0.30
NOISE_FLOOR = 1e-4

# The Chao knots of the cmn pack's tones (packs/cmn/cmn.toml). The pack's neutral tone depends on
# context; here it is a fixed short fall from 3 to 2, rendered at half the syllable duration.
CHAO = {"1": [5.0, 5.0], "2": [3.0, 5.0], "3": [2.0, 1.0, 4.0], "4": [5.0, 1.0], "5": [3.0, 2.0]}
NEUTRAL_LENGTH = 0.5  # the neutral tone's share of the syllable duration


def chao_to_hz(chao: np.ndarray) -> np.ndarray:
    """Hz for Chao values: the octave from FLOOR_HZ to CEIL_HZ divided into Chao 1..5."""
    return FLOOR_HZ * (CEIL_HZ / FLOOR_HZ) ** ((chao - 1.0) / 4.0)


def syllable(tone: str, dur: float = SYLLABLE_S) -> np.ndarray:
    """One syllable of `tone` ("1".."5") lasting `dur` seconds (half that for the neutral "5")."""
    n = round(dur * (NEUTRAL_LENGTH if tone == "5" else 1.0) * RATE)
    knots = CHAO[tone]
    chao = np.interp(np.linspace(0.0, 1.0, n), np.linspace(0.0, 1.0, len(knots)), knots)
    phase = 2.0 * np.pi * np.cumsum(chao_to_hz(chao)) / RATE
    wave = sum(np.sin(k * phase) / k for k in range(1, 9))
    ramp = round(0.03 * RATE)
    envelope = np.ones(n)
    envelope[:ramp] = np.sin(0.5 * np.pi * np.arange(ramp) / ramp) ** 2
    envelope[-ramp:] = envelope[:ramp][::-1]
    wave = wave * envelope
    return 0.5 * wave / np.abs(wave).max()


def utterance(
    tones: list[str], seed: int = 0, *, syllable_s: float = SYLLABLE_S, gap_s: float = GAP_S
) -> np.ndarray:
    """A 16 kHz float32 utterance saying `tones` (each "1".."5"), one syllable per tone, with
    syllables of `syllable_s` seconds and gaps of `gap_s` seconds between them."""
    rng = np.random.default_rng(seed)
    gap = np.zeros(round(gap_s * RATE))
    edge = np.zeros(round(EDGE_S * RATE))
    parts: list[np.ndarray] = [edge]
    for i, tone in enumerate(tones):
        if i:
            parts.append(gap)
        parts.append(syllable(tone, syllable_s))
    parts.append(edge)
    x = np.concatenate(parts)
    x = x + NOISE_FLOOR * rng.standard_normal(len(x))
    return x.astype(np.float32)


def candidate(tones: list[str]) -> Candidate:
    return Candidate(id="-".join(tones), tones=list(tones), labels=[])


def write_clip(
    root: Path,
    cid: str,
    pcm: np.ndarray,
    *,
    intended: list[str],
    set: str = "gate",
    pair: str | None = None,
    label: str = "correct",
    speaker: str = "dj",
    distractors: list[list[str]] | None = None,
    produced: list[str] | None = None,
    source: str = "synthetic-world",
) -> Clip:
    """Write `pcm` (16 kHz mono samples) to `<root>/<cid>.wav` and return its manifest `Clip`,
    whose path is relative to `root`. `intended` is the reading the clip aims for; `produced` the
    tones actually spoken, if known (`produced_tones` is null otherwise); `source` is its
    data-register id."""
    root.mkdir(parents=True, exist_ok=True)
    wavfile.write(root / f"{cid}.wav", RATE, np.asarray(pcm, dtype=np.float32))
    return Clip(
        id=cid,
        path=f"{cid}.wav",
        speaker=speaker,
        set=set,  # type: ignore[arg-type]
        pair=pair,
        label=label,  # type: ignore[arg-type]
        intended=candidate(intended),
        distractors=[candidate(d) for d in distractors or []],
        produced_tones=None if produced is None else list(produced),
        condition=Condition(noise="none", distance="synthetic"),
        source=source,
        synthetic={"generator": "tests/support.py"} if set == "synthetic" else None,
    )


def make_clip(
    root: Path,
    cid: str,
    produced: list[str],
    *,
    intended: list[str] | None = None,
    set: str = "gate",
    pair: str | None = None,
    label: str = "correct",
    speaker: str = "dj",
    distractors: list[list[str]] | None = None,
    seed: int = 0,
    syllable_s: float = SYLLABLE_S,
    gap_s: float = GAP_S,
    source: str = "synthetic-world",
) -> Clip:
    """Synthesise `<root>/<cid>.wav` speaking `produced` (see `utterance`) and return its manifest
    `Clip`, whose intended reading is `intended` (default: what was produced)."""
    return write_clip(
        root,
        cid,
        utterance(produced, seed, syllable_s=syllable_s, gap_s=gap_s),
        intended=intended or produced,
        set=set,
        pair=pair,
        label=label,
        speaker=speaker,
        distractors=distractors,
        produced=produced,
        source=source,
    )


def write_manifest(path: Path, clips: list[Clip]) -> Path:
    path.write_text("".join(c.model_dump_json() + "\n" for c in clips), encoding="utf-8")
    return path


def gate_corpus(root: Path, source: str = "synthetic-world") -> list[Clip]:
    """Two gate pairs (four clips): each pair speaks its intended tones once correctly and once
    with the middle tone changed."""
    return [
        make_clip(
            root, "gate-01-correct", ["4", "1", "3"], pair="gate-01", label="correct", source=source
        ),
        make_clip(
            root, "gate-01-error", ["4", "2", "3"], intended=["4", "1", "3"],
            pair="gate-01", label="tone_error", source=source,
        ),  # fmt: skip
        make_clip(
            root, "gate-02-correct", ["1", "2", "4"], pair="gate-02", label="correct", source=source
        ),
        make_clip(
            root, "gate-02-error", ["1", "3", "4"], intended=["1", "2", "4"],
            pair="gate-02", label="tone_error", source=source,
        ),  # fmt: skip
    ]
