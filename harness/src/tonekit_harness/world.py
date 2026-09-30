"""A thin wrapper over WORLD (via pyworld): analysis into f0, spectral envelope and aperiodicity on
tonekit's 10 ms grid, and resynthesis. Everything else in the synthetic corpus builds on this.

Synthetic audio is for tests and diagnostics only; it is never used to fit shipped calibration.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np

with warnings.catch_warnings():
    # pyworld 0.3.5 imports pkg_resources (only to read its own version), which setuptools 80
    # warns about. Nothing else in the harness imports it, so the filter stays scoped to here.
    warnings.filterwarnings("ignore", message="pkg_resources is deprecated", category=UserWarning)
    import pyworld

from .ingest import TARGET_SR

HOP = 160  # tonekit's hop: 10 ms at 16 kHz
FRAME_PERIOD_MS = 10.0
F0_FLOOR = 50.0  # the same search range as tonekit's pYIN (50-600 Hz)
F0_CEIL = 600.0


@dataclass(frozen=True)
class World:
    """WORLD's parameters, one row per 10 ms frame."""

    f0: np.ndarray  # (n,) Hz, float64; 0 where unvoiced
    sp: np.ndarray  # (n, fft_size / 2 + 1) spectral envelope (power)
    ap: np.ndarray  # (n, fft_size / 2 + 1) aperiodicity (0..1)


def n_frames(n_samples: int) -> int:
    """Frames on tonekit's grid: frame i is centred at sample i * HOP."""
    return n_samples // HOP + 1


def analyse(pcm: np.ndarray) -> World:
    """Harvest (with StoneMask), CheapTrick and D4C of 16 kHz mono samples, on tonekit's grid.

    WORLD's grid is `floor(1000 * n / fs / period) + 1` frames, which is exactly `n // 160 + 1`,
    so no trimming or padding is needed; that is asserted rather than assumed."""
    x = np.asarray(pcm, dtype=np.float64)
    f0, t = pyworld.harvest(
        x, TARGET_SR, f0_floor=F0_FLOOR, f0_ceil=F0_CEIL, frame_period=FRAME_PERIOD_MS
    )
    f0 = pyworld.stonemask(x, f0, t, TARGET_SR)
    fft_size = pyworld.get_cheaptrick_fft_size(TARGET_SR, F0_FLOOR)
    sp = pyworld.cheaptrick(x, f0, t, TARGET_SR, f0_floor=F0_FLOOR, fft_size=fft_size)
    ap = pyworld.d4c(x, f0, t, TARGET_SR, fft_size=fft_size)
    if len(f0) != n_frames(len(x)):
        raise RuntimeError(f"WORLD gave {len(f0)} frames for {len(x)} samples")
    return World(f0=f0, sp=sp, ap=ap)


def synthesise(world: World, n_samples: int | None = None) -> np.ndarray:
    """The waveform (float32, 16 kHz) of `world`. WORLD emits `HOP` samples per frame, so the last
    frame overshoots the source; the result is cut or zero-padded to `n_samples` (default: the
    source's length, `(frames - 1) * HOP`)."""
    n_samples = (len(world.f0) - 1) * HOP if n_samples is None else n_samples
    y = pyworld.synthesize(world.f0, world.sp, world.ap, TARGET_SR, FRAME_PERIOD_MS)
    out = np.zeros(n_samples, dtype=np.float32)
    n = min(n_samples, len(y))
    out[:n] = y[:n]
    return out
