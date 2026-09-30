"""f0 tracks on tonekit's 10 ms grid: frame i is centred at i * 160 samples and a clip of n samples
has n // 160 + 1 frames, whoever computed the track.

- `pyin_track` reads tonekit's own track back out of an Analysis.
- `swiftf0_track` runs SwiftF0 and resamples its frames onto the grid, as the `F0Track` JSON that
  `tonekit_py.analyze(..., f0_json=...)` accepts. `resample` is that step on its own.
- `provider_track` and `provider_identity` are the named providers `evaluate.run(f0=...)` takes.

A track is a `list[float | None]` in Hz, `None` where unvoiced. A frame is voiced when it has a
pitch (ruling R32: `voiced_p` is only a confidence weight), which is how tonekit reads it too.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from functools import cache
from importlib import metadata

import numpy as np

SAMPLE_RATE = 16_000
HOP = 160  # samples per grid frame

# SwiftF0 is given the band of tonekit's own pYIN (50-600 Hz), so a frame whose best pitch lies
# outside it is unvoiced rather than an octave error that pYIN could not make.
F0_MIN_HZ = 50.0
F0_MAX_HZ = 600.0

# SwiftF0 calls a frame voiced at confidence 0.5 and above; the grid frames need 0.9, the bakeoff's
# rule for a voiced frame.
SWIFTF0_VOICED = 0.5
GRID_VOICED = 0.9


def _hz(frames: Sequence[dict]) -> list[float | None]:
    """The pitch of each F0Track frame, `None` unless it is a finite positive number (the frames
    tonekit would call unvoiced)."""
    out: list[float | None] = []
    for frame in frames:
        hz = frame["hz"]
        out.append(hz if hz is not None and math.isfinite(hz) and hz > 0 else None)
    return out


def track_hz(f0_json: str) -> list[float | None]:
    """The pitch of each frame of an `F0Track` JSON."""
    return _hz(json.loads(f0_json)["frames"])


def pyin_track(analysis_json: str) -> list[float | None]:
    """tonekit's own f0 track, as the Analysis JSON has it (after octave repair)."""
    return _hz(json.loads(analysis_json)["f0"]["frames"])


# ---- SwiftF0 -----------------------------------------------------------------------------------


def resample(
    timestamps: Sequence[float],
    pitch_hz: Sequence[float],
    confidence: Sequence[float],
    n_frames: int,
) -> list[dict]:
    """SwiftF0's frames on the 10 ms grid, as F0Track frames `{"hz": float | None, "voiced_p": float}`.

    `timestamps` (seconds) are the frames' centres: SwiftF0's frame k is centred at k * 256
    samples, 16 ms apart. For the grid frame at time t, between SwiftF0 frames a and b:

    - `voiced_p` is the confidence interpolated linearly between a and b;
    - the frame is voiced iff that is at least 0.9 and the nearest of a and b (the earlier on a
      tie) is voiced by SwiftF0's own rule (confidence at least 0.5, and a positive pitch);
    - `hz` is then interpolated in semitones between a and b when both are voiced, else it is the
      pitch of the one that is (an unvoiced frame's pitch is never used); otherwise `None`.

    A grid frame outside the span from the first to the last SwiftF0 frame is unvoiced with
    `voiced_p` 0. It is `n_frames` frames long.
    """
    at = np.round(np.asarray(timestamps, dtype=np.float64) * SAMPLE_RATE)  # in samples
    hz = np.asarray(pitch_hz, dtype=np.float64)
    conf = np.asarray(confidence, dtype=np.float64)
    usable = (conf >= SWIFTF0_VOICED) & np.isfinite(hz) & (hz > 0)
    st = 12.0 * np.log2(np.where(usable, hz, 55.0) / 55.0)

    grid = np.arange(n_frames, dtype=np.float64) * HOP
    covered = (grid >= at[0]) & (grid <= at[-1])
    grid = np.clip(grid, at[0], at[-1])
    lo = np.clip(np.searchsorted(at, grid, side="right") - 1, 0, max(len(at) - 2, 0))
    hi = np.minimum(lo + 1, len(at) - 1)
    span = at[hi] - at[lo]
    w = np.divide(grid - at[lo], span, out=np.zeros_like(grid), where=span > 0)

    voiced_p = np.where(covered, (1.0 - w) * conf[lo] + w * conf[hi], 0.0)
    nearest = np.where(w > 0.5, hi, lo)
    voiced = covered & (voiced_p >= GRID_VOICED) & usable[nearest]
    both = usable[lo] & usable[hi]
    semitones = np.where(both, (1.0 - w) * st[lo] + w * st[hi], np.where(usable[lo], st[lo], st[hi]))
    grid_hz = 55.0 * 2.0 ** (semitones / 12.0)
    return [
        {"hz": float(h) if v else None, "voiced_p": float(np.clip(p, 0.0, 1.0))}
        for h, v, p in zip(grid_hz, voiced, voiced_p, strict=True)
    ]


def _swiftf0_identity() -> str:
    return f"swift-f0 {metadata.version('swift-f0')}"


@cache
def _detector():
    """One SwiftF0 for the process: the model ships inside the package (nothing is downloaded), and
    one thread makes its output reproducible."""
    from swift_f0 import SwiftF0  # imported here: onnxruntime is slow to load

    return SwiftF0(threads=1, spin=False)


def swiftf0_track(pcm: np.ndarray) -> str:
    """SwiftF0's f0 for 16 kHz mono `pcm`, on tonekit's grid, as `F0Track` JSON with the provider
    `"swift-f0 <version>"` (see `resample`)."""
    pcm = np.asarray(pcm, dtype=np.float32)
    found = _detector().detect(pcm, SAMPLE_RATE, fmin=F0_MIN_HZ, fmax=F0_MAX_HZ)
    frames = resample(found.timestamps, found.pitch_hz, found.confidence, len(pcm) // HOP + 1)
    return json.dumps({"frames": frames, "provider": _swiftf0_identity()})


# ---- named providers ---------------------------------------------------------------------------

# name -> (identity, track): `identity` says which implementation, for the analysis cache key.
_PROVIDERS: dict[str, tuple[Callable[[], str], Callable[[np.ndarray], str]]] = {
    "swift-f0": (_swiftf0_identity, swiftf0_track),
}
PROVIDERS = tuple(_PROVIDERS)


def _provider(name: str):
    try:
        return _PROVIDERS[name]
    except KeyError:
        raise ValueError(
            f"unknown f0 provider {name!r} (known: {', '.join(PROVIDERS)})"
        ) from None


def provider_identity(name: str) -> str:
    """The provider's name and version, e.g. `"swift-f0 0.3.0"`."""
    return _provider(name)[0]()


def provider_track(name: str, pcm: np.ndarray) -> str:
    """The `F0Track` JSON the named provider computes for `pcm`."""
    return _provider(name)[1](pcm)
