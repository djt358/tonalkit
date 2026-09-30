"""Helpers shared by the synthesis tests (WORLD, sources, families, `perturb`, corpora). The
fixtures that use them are in conftest.py. Synthetic audio here is the numpy harmonic voice of
support.py, never DJ's audio."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from support import utterance, write_clip

from tonekit_harness.source import Source

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"
HOP = 160


def quiet_clip(root: Path, cid: str, tones: list[str], **kw):
    """A support-voice clip at half amplitude, so resynthesis plus noise cannot clip."""
    return write_clip(root, cid, 0.5 * utterance(tones), intended=tones, produced=tones, **kw)


def semitones(hz: list[float | None]) -> np.ndarray:
    return np.array([np.nan if h is None else 12 * np.log2(h / 55.0) for h in hz])


def core(src: Source, truth: list[float | None], index: int) -> np.ndarray:
    """The truth's semitones over syllable `index`'s voiced core, unvoiced frames dropped."""
    start, end = src.voice.extents[index]
    st = semitones(truth)[start:end]
    return st[~np.isnan(st)]
