"""The calibration's evidence for creaky tails (ruling R108): per tone, how often a pitched
syllable of that tone ends in creak (speech with a vowel's spectrum and no pitch right after its
last pitched frame), at the end of a phrase and elsewhere."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .observe import SHAPE, Observation
from .unpitched import log_tables, place_rates


def tail_rates(observations: Iterable[Observation], tones: Sequence[str], final: bool) -> dict[str, float]:
    """P(creaky tail | tone) over the syllables with a shape (`unpitched.place_rates`)."""
    return place_rates(
        observations, tones, final, counted=lambda o: o.kind == SHAPE, hit=lambda o: o.creaky
    )


def fit_creaky_tail(observations: Sequence[Observation], tones: Sequence[str]) -> dict:
    """The calibration's `creaky_tail` section: `ln P(creaky tail | tone)` per tone, at the end of
    a phrase (`phrase_final`) and elsewhere (`other`), rounded to 4 decimals."""
    return log_tables(tail_rates, observations, tones)
