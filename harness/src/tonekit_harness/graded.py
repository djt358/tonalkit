"""The `graded` families: the tone is kept but distorted by a controlled amount, so there is no
binary truth to search against."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from .family import Bound, Family
from .voice import HOP_MS, KNOT_MARGIN, Voice, render


def turning_knot(knots: Sequence[float]) -> int:
    """The index of the interior knot at the contour's turning point: the interior extremum (a
    knot where the contour changes direction), the most pronounced one if there are several. A
    contour with no interior extremum (monotone) has its middle knot."""
    best, best_height = len(knots) // 2, 0.0
    for j in range(1, len(knots) - 1):
        before, after = knots[j] - knots[j - 1], knots[j + 1] - knots[j]
        height = abs(after - before)  # how sharply the direction changes there
        if before * after < 0 and height > best_height:
            best, best_height = j, height
    return best


class RangeCompress(Family):
    """The whole utterance's pitch range narrowed about the register's midline."""

    name = "range_compress"
    label = "graded"
    bounds = {"factor": Bound(0.4, 0.8)}

    def contour(self, voice: Voice, p: Mapping) -> np.ndarray:
        mid = (voice.floor + voice.ceil) / 2.0
        return mid + p["factor"] * (voice.st - mid)


class _KnotShift(Family):
    """A syllable's own tone drawn with one knot moved."""

    label = "graded"
    indexed = True

    def syllables(self, voice: Voice) -> list[int]:
        return [i for i in voice.targetable() if voice.pack.has_contour(voice.tones[i])]

    def knots(self, voice: Voice, p: Mapping) -> tuple[float, ...]:
        return voice.pack.contour(voice.tones[p["index"]])


class TurnShift(_KnotShift):
    """The turning point (the interior extremum of a tone with an interior knot, see
    `turning_knot`) moved in time."""

    name = "turn_shift"
    bounds = {"ms": Bound(40.0, 120.0, signed=True)}

    def syllables(self, voice: Voice) -> list[int]:
        drawable = super().syllables(voice)
        return [i for i in drawable if len(voice.pack.contour(voice.tones[i])) >= 3]

    def contour(self, voice: Voice, p: Mapping) -> np.ndarray:
        knots = self.knots(voice, p)
        start, end = voice.extents[p["index"]]  # type: ignore[misc]
        times = np.linspace(0.0, 1.0, len(knots))
        j = turning_knot(knots)
        shifted = times[j] + p["ms"] / ((end - start - 1) * HOP_MS)
        times[j] = np.clip(shifted, times[j - 1] + KNOT_MARGIN, times[j + 1] - KNOT_MARGIN)
        return render(voice, p["index"], knots, times)


class OnsetShift(_KnotShift):
    """The first knot raised or lowered."""

    name = "onset_shift"
    bounds = {"chao": Bound(0.5, 1.5, signed=True)}

    def contour(self, voice: Voice, p: Mapping) -> np.ndarray:
        knots = list(self.knots(voice, p))
        knots[0] += p["chao"]
        return render(voice, p["index"], knots)


class OffsetShift(_KnotShift):
    """The last knot raised or lowered."""

    name = "offset_shift"
    bounds = {"chao": Bound(0.5, 1.5, signed=True)}

    def contour(self, voice: Voice, p: Mapping) -> np.ndarray:
        knots = list(self.knots(voice, p))
        knots[-1] += p["chao"]
        return render(voice, p["index"], knots)
