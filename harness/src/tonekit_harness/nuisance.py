"""The `correct` families: nuisance factors (noise, register, rate) a listener would accept, so
the label stays `correct`; and the `identity` control every family is compared with."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import numpy as np

from .family import Bound, Family
from .voice import Voice


def pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """Unit-RMS pink (1/f power) noise of `n` samples: white noise shaped in frequency."""
    spectrum = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(spectrum), dtype=float)
    f[0] = 1.0
    spectrum /= np.sqrt(f)
    spectrum[0] = 0.0
    noise = np.fft.irfft(spectrum, n)
    return noise / np.sqrt(np.mean(noise**2))


class Identity(Family):
    """WORLD resynthesis of the source's own f0: the control every other family is compared with."""

    name = "identity"
    label = "correct"
    searchable = False


class Noise(Family):
    """Noise added after resynthesis at `snr_db` relative to the speech power over voiced frames:
    seeded pink noise, or `noise_wav` (a 16 kHz mono recording, looped from a random start)."""

    name = "noise"
    label = "correct"
    bounds = {"snr_db": Bound(5.0, 20.0)}
    optional_paths = ("noise_wav",)

    def audio(self, y, voiced, p, rng, bed):
        if bed is None:
            noise = pink_noise(len(y), rng)
        else:
            if not np.any(bed):
                raise self._fail("the noise recording is silent")
            start = int(rng.integers(len(bed)))
            noise = np.resize(np.roll(bed, -start), len(y)).astype(np.float64)
            noise = noise / np.sqrt(np.mean(noise**2))
        speech = y[voiced] if voiced.any() else y
        speech_rms = np.sqrt(np.mean(speech.astype(np.float64) ** 2))
        return (y + speech_rms / 10.0 ** (p["snr_db"] / 20.0) * noise).astype(np.float32)

    def condition_noise(self, p: Mapping) -> str:
        kind = "pink" if p["noise_wav"] is None else Path(p["noise_wav"]).stem
        return f"{kind} {p['snr_db']:g} dB"


class RegisterShift(Family):
    """The whole f0 track moved up or down, `st` semitones."""

    name = "register_shift"
    label = "correct"
    bounds = {"st": Bound(-6.0, 6.0)}

    def contour(self, voice: Voice, p: Mapping) -> np.ndarray:
        return voice.st + p["st"]


class Rate(Family):
    """The whole utterance sped up (`factor` > 1: shorter) or slowed down."""

    name = "rate"
    label = "correct"
    bounds = {"factor": Bound(0.8, 1.25)}

    def speed(self, p: Mapping) -> float:
        return p["factor"]
