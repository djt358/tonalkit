"""The calibration's evidence for unpitched syllables (ruling R103): per tone, how often a syllable
of that tone comes out with speech energy and a vowel's spectrum but no pitch, at the end of a
phrase and elsewhere. `place_rates` and `log_tables` are shared with the creaky-tail evidence
(`tail`, ruling R108)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence

from .observe import SHAPE, UNPITCHED, Observation

# Pseudo-observations at the pooled rate added to every tone's count: a tone seen a few times
# keeps close to the pooled rate rather than to 0 or 1.
SMOOTHING = 4.0
# No rate is taken below this (a tone never seen unpitched is still not impossible).
MIN_RATE = 0.005

Rates = Callable[[Iterable[Observation], Sequence[str], bool], dict[str, float]]


def place_rates(
    observations: Iterable[Observation],
    tones: Sequence[str],
    final: bool,
    counted: Callable[[Observation], bool],
    hit: Callable[[Observation], bool],
) -> dict[str, float]:
    """P(`hit` | tone) at the phrase's end (`final`) or elsewhere, per tone: the share of the
    `counted` syllables of clips read as the card asks (`correct`: an error card's tone may not be
    what was said) that are hits, smoothed towards the pooled share by `SMOOTHING`
    pseudo-observations and kept within [`MIN_RATE`, 1 - `MIN_RATE`]. A tone with no syllable
    there gets the pooled share (Laplace's (hits + 1) / (n + 2) over every tone)."""
    measured = [o for o in observations if o.final == final and o.label == "correct" and counted(o)]
    pooled = (sum(map(hit, measured)) + 1) / (len(measured) + 2)
    out = {}
    for tone in tones:
        mine = [o for o in measured if o.tone == tone]
        rate = (sum(map(hit, mine)) + SMOOTHING * pooled) / (len(mine) + SMOOTHING)
        out[tone] = min(max(rate, MIN_RATE), 1.0 - MIN_RATE)
    return out


def log_tables(rates_of: Rates, observations: Sequence[Observation], tones: Sequence[str]) -> dict:
    """A calibration evidence section: `ln` of `rates_of` per tone at the end of a phrase
    (`phrase_final`) and elsewhere (`other`), rounded to 4 decimals."""
    return {
        place: {t: round(math.log(r), 4) for t, r in rates_of(observations, tones, final).items()}
        for place, final in (("phrase_final", True), ("other", False))
    }


def rates(observations: Iterable[Observation], tones: Sequence[str], final: bool) -> dict[str, float]:
    """P(unpitched | tone) (`place_rates` over the measured syllables, those with a shape or
    unpitched: missed ones say nothing)."""
    return place_rates(
        observations,
        tones,
        final,
        counted=lambda o: o.kind in (SHAPE, UNPITCHED),
        hit=lambda o: o.kind == UNPITCHED,
    )


def fit_unpitched(observations: Sequence[Observation], tones: Sequence[str]) -> dict:
    """The calibration's `unpitched` section: `ln P(unpitched | tone)` per tone, at the end of a
    phrase (`phrase_final`) and elsewhere (`other`), rounded to 4 decimals."""
    return log_tables(rates, observations, tones)
