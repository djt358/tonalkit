"""The calibration's evidence for unpitched syllables (ruling R103): per tone, how often a syllable
of that tone comes out with speech energy and a vowel's spectrum but no pitch, at the end of a
phrase and elsewhere."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

from .observe import SHAPE, UNPITCHED, Observation

# Pseudo-observations at the pooled rate added to every tone's count: a tone seen a few times
# keeps close to the pooled rate rather than to 0 or 1.
SMOOTHING = 4.0
# No rate is taken below this (a tone never seen unpitched is still not impossible).
MIN_RATE = 0.005


def rates(observations: Iterable[Observation], tones: Sequence[str], final: bool) -> dict[str, float]:
    """P(unpitched | tone) at the phrase's end (`final`) or elsewhere, per tone: the share of the
    measured syllables (with a shape or unpitched; missed ones say nothing) that were unpitched,
    smoothed towards the pooled share by `SMOOTHING` pseudo-observations and kept within
    [`MIN_RATE`, 1 - `MIN_RATE`]. A tone with no syllable there gets the pooled share."""
    measured = [o for o in observations if o.final == final and o.kind in (SHAPE, UNPITCHED)]
    total = len(measured)
    pooled = (sum(o.kind == UNPITCHED for o in measured) + 1) / (total + 2)
    out = {}
    for tone in tones:
        mine = [o for o in measured if o.tone == tone]
        hits = sum(o.kind == UNPITCHED for o in mine)
        rate = (hits + SMOOTHING * pooled) / (len(mine) + SMOOTHING)
        out[tone] = min(max(rate, MIN_RATE), 1.0 - MIN_RATE)
    return out


def fit_unpitched(observations: Sequence[Observation], tones: Sequence[str]) -> dict:
    """The calibration's `unpitched` section: `ln P(unpitched | tone)` per tone, at the end of a
    phrase (`phrase_final`) and elsewhere (`other`), rounded to 4 decimals."""
    return {
        place: {t: round(math.log(r), 4) for t, r in rates(observations, tones, final).items()}
        for place, final in (("phrase_final", True), ("other", False))
    }
