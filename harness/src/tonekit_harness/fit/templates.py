"""The pack's tone templates and their spreads, fitted on calibration speakers (ruling R109).

One template per full tone and place in the phrase (its last syllable, or any other), the median
of the measured contours, from the syllables whose placement does not depend on the templates
being fitted: clips with exactly one nucleus per syllable, read as the card asks (`correct`), and
whose pitch does not give way to creak (a creaky tail cuts the contour short: what is left is not
the tone's shape, and the tail is scored as evidence of its own, ruling R108). The
spreads are the maximum-likelihood σ of the pack's score (spec §7.1) over those syllables, the
worst-fitting tenth left out (misplaced or mismeasured syllables)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .observe import SHAPE, Observation

FULL_TONES = ("1", "2", "3", "4")
CONTOUR_POINTS = 10
# Knots of a fitted template, at these fractions of the syllable: five are enough for every
# Mandarin contour (a dip's turning point included) and smooth over per-point noise.
KNOT_AT = (0.0, 0.25, 0.5, 0.75, 1.0)
# A place needs this many syllables for a template of its own; with fewer, the tone's syllables
# from both places are pooled.
MIN_GROUP = 6
# The largest residuals left out of the spreads.
TRIM = 0.1
# Weight of a contour point, as the score has it: max(voiced weight, 0.25).
MIN_POINT_WEIGHT = 0.25


@dataclass(frozen=True)
class Template:
    tone: str
    final: bool
    knots: tuple[float, ...]
    n: int  # syllables it was fitted on


@dataclass(frozen=True)
class Spread:
    contour: float
    onset: float
    offset: float
    n: int


def usable(o: Observation) -> bool:
    """A syllable a template may be fitted on (see the module docs)."""
    return (
        o.kind == SHAPE
        and o.shape is not None
        and o.clean
        and o.label == "correct"
        and not o.creaky
        and o.tone in FULL_TONES
        and all(math.isfinite(v) for v in o.shape["contour"])
    )


def expand(knots: Sequence[float], n: int = CONTOUR_POINTS) -> np.ndarray:
    """Knots spread evenly over the syllable, linearly interpolated onto `n` points (as the pack
    expands them)."""
    return np.interp(np.linspace(0.0, 1.0, n), np.linspace(0.0, 1.0, len(knots)), knots)


def knots_of(contour: np.ndarray) -> tuple[float, ...]:
    """The contour (10 points) read at [`KNOT_AT`], to 2 decimals."""
    u = np.linspace(0.0, 1.0, len(contour))
    return tuple(round(float(np.interp(at, u, contour)), 2) for at in KNOT_AT)


def fit_templates(
    observations: Sequence[Observation],
    prior: dict[tuple[str, bool], np.ndarray] | None = None,
    strength: float = 0.0,
) -> list[Template]:
    """One template per full tone and place: the pointwise median contour of its usable
    syllables, or of the tone's syllables in both places when a place has fewer than
    `MIN_GROUP`. A tone with no usable syllable gets none (the pack keeps its own).

    With a `prior` (10-point contours by `(tone, final)`, the seed pack's expectations) and a
    `strength` κ > 0, the median is shrunk towards the prior as if κ syllables had shown it:
    `(n·median + κ·prior) / (n + κ)`. Two speakers are too few for the median alone to stand for
    every speaker (ruling R109); κ is chosen by fitting on one speaker and scoring the other."""
    ok = [o for o in observations if usable(o)]
    out = []
    for tone in FULL_TONES:
        mine = [o for o in ok if o.tone == tone]
        for final in (False, True):
            group = [o for o in mine if o.final == final]
            if len(group) < MIN_GROUP:
                group = mine
            if not group:
                continue
            median = np.median(np.array([o.shape["contour"] for o in group]), axis=0)
            if prior is not None and strength > 0 and (tone, final) in prior:
                n = len(group)
                median = (n * median + strength * prior[(tone, final)]) / (n + strength)
            out.append(Template(tone, final, knots_of(median), len(group)))
    return out


def fit_spread(observations: Sequence[Observation], templates: Sequence[Template]) -> Spread | None:
    """The σ of the score's three terms on the usable syllables against their templates:
    σ_contour² is the mean weighted mean square of the contour residual, σ_onset² and
    σ_offset² half the mean squared onset and offset residuals (each term's maximum-likelihood
    value), each with its largest `TRIM` left out. None without a usable syllable."""
    by_key = {(t.tone, t.final): expand(t.knots) for t in templates}
    wms, on, off = [], [], []
    for o in observations:
        if not usable(o) or (o.tone, o.final) not in by_key:
            continue
        c = np.array(o.shape["contour"])
        t = by_key[(o.tone, o.final)]
        w = np.maximum(np.array(o.shape["voiced_weights"]), MIN_POINT_WEIGHT)
        wms.append(float(np.sum(w * (c - t) ** 2) / np.sum(w)))
        on.append((o.shape["onset"] - t[0]) ** 2)
        off.append((o.shape["offset"] - t[-1]) ** 2)
    if not wms:
        return None

    def trimmed_mean(v: list[float]) -> float:
        v = sorted(v)
        keep = v[: max(1, int(round(len(v) * (1.0 - TRIM))))]
        return sum(keep) / len(keep)

    return Spread(
        contour=round(math.sqrt(trimmed_mean(wms)), 3),
        onset=round(math.sqrt(0.5 * trimmed_mean(on)), 3),
        offset=round(math.sqrt(0.5 * trimmed_mean(off)), 3),
        n=len(wms),
    )
