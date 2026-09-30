"""The base of every perturbation family: `Bound`, `SynthError` and the `Family` class with its
parameter validation, bound resolution and random sampling. The concrete families are in
`tone_errors`, `graded` and `nuisance`; `families` is their registry.

A family says which syllables it may target, which parameter values are allowed, and how it
changes what WORLD resynthesises: the f0 track (`contour`), the time base (`speed`) or the audio
(`audio`). There is no I/O here.

- `tone_error` families change the tone the syllable carries: the label is `tone_error`.
- `graded` families keep the tone but distort it by a controlled amount: there is no binary truth.
- `correct` families are nuisance factors a listener would accept: the label is `correct`.

Magnitudes are spec §9's. Calling a family with a value outside them is a `SynthError`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral, Real
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .voice import Voice


class SynthError(ValueError):
    """A perturbation or its source is invalid; the message names the family and the parameter."""


@dataclass(frozen=True)
class Bound:
    """The values a numeric parameter may take: `lo..hi`, or, when `signed`, a magnitude in
    `lo..hi` with either sign."""

    lo: float
    hi: float
    signed: bool = False

    def contains(self, x: float) -> bool:
        return self.lo <= (abs(x) if self.signed else x) <= self.hi

    def __str__(self) -> str:
        return f"{'a magnitude in ' if self.signed else ''}[{self.lo:g}, {self.hi:g}]"


class Family:
    """Base class: a family that leaves everything as it is. Subclasses set the class attributes
    and override the hooks they change."""

    name: str
    label: str  # "tone_error", "graded" or "correct"
    bounds: Mapping[str, Bound] = {}  # numeric parameters and their spec §9 magnitudes
    indexed = False  # takes `index`: the syllable to perturb
    takes_to = False  # takes `to`: the tone to render there
    optional_paths: tuple[str, ...] = ()  # optional file-path parameters (default None)
    searchable = True  # sampled by `tkh synth` and the adversary

    # -- which syllables and tones ------------------------------------------------------------

    def syllables(self, voice: Voice) -> list[int]:
        """The syllables `index` may name."""
        return voice.targetable()

    def choices(self, voice: Voice, index: int) -> list[str]:
        """The tones `to` may name for syllable `index`."""
        return []

    # -- what the family changes --------------------------------------------------------------

    def contour(self, voice: Voice, p: Mapping) -> np.ndarray:
        """The f0 track to synthesise, in semitones (NaN where unvoiced), on the source's grid."""
        return voice.st.copy()

    def speed(self, p: Mapping) -> float:
        """The time scale: above 1 is faster, so shorter."""
        return 1.0

    def audio(
        self,
        y: np.ndarray,
        voiced: np.ndarray,
        p: Mapping,
        rng: np.random.Generator,
        bed: np.ndarray | None,
    ) -> np.ndarray:
        """`y` after resynthesis. `voiced` marks the samples of voiced frames; `bed` is the noise
        recording, if the caller gave one."""
        return y

    def produced(self, voice: Voice, p: Mapping) -> list[str] | None:
        """The tones the audio now carries, or None if it carries the source's."""
        return None

    def condition_noise(self, p: Mapping) -> str | None:
        """The row's `condition.noise` if the family changes it."""
        return None

    # -- parameters ---------------------------------------------------------------------------

    def _fail(self, message: str) -> SynthError:
        return SynthError(f"{self.name}: {message}")

    def validate(self, voice: Voice, params: Mapping) -> dict:
        """`params` checked against the source and the bounds, or `SynthError`. The result has
        exactly the family's parameters, numbers as floats."""
        allowed = [*(["index"] if self.indexed else []), *(["to"] if self.takes_to else [])]
        allowed += [*self.bounds, *self.optional_paths]
        unknown = sorted(set(params) - set(allowed))
        if unknown:
            takes = ", ".join(allowed) or "none"
            raise self._fail(f"unknown parameter {unknown[0]!r} (takes: {takes})")
        required = [n for n in allowed if n not in self.optional_paths]
        missing = [n for n in required if n not in params]
        if missing:
            raise self._fail(f"missing parameter {missing[0]!r}")

        out: dict = {}
        index = params.get("index")
        if self.indexed:
            ok = self.syllables(voice)
            # any integer type (a numpy index from a search loop is fine); recorded as a plain int
            if isinstance(index, bool) or not isinstance(index, Integral) or index not in ok:
                raise self._fail(
                    f"index {index!r} is not a syllable this family can target (targetable: {ok})"
                )
            out["index"] = int(index)
        if self.takes_to:
            ok_tones = self.choices(voice, index)
            if params["to"] not in ok_tones:
                raise self._fail(f"to {params['to']!r} must be one of {ok_tones}")
            out["to"] = params["to"]
        for name, bound in self.bounds.items():
            x = params[name]
            if isinstance(x, bool) or not isinstance(x, Real) or not np.isfinite(x):
                raise self._fail(f"{name} {x!r} is not a finite number")
            if not bound.contains(x):
                raise self._fail(f"{name} {x:g} is outside {bound}")
            out[name] = float(x)
        for name in self.optional_paths:
            value = params.get(name)
            if value is not None and not isinstance(value, str):
                raise self._fail(f"{name} {value!r} is not a path")
            out[name] = value
        return out

    def resolve_bounds(
        self, overrides: Mapping[str, tuple[float, float]] | None
    ) -> dict[str, tuple[float, float]]:
        """The (lo, hi) to sample each numeric parameter in: the spec's, or `overrides`, which
        must lie inside them (a bound is a magnitude for a signed parameter)."""
        overrides = overrides or {}
        unknown = sorted(set(overrides) - set(self.bounds))
        if unknown:
            raise self._fail(f"no numeric parameter {unknown[0]!r} to bound")
        resolved = {}
        for name, spec in self.bounds.items():
            lo, hi = overrides.get(name, (spec.lo, spec.hi))
            if not (spec.lo <= lo <= hi <= spec.hi):
                raise self._fail(
                    f"bounds for {name} ({lo:g}, {hi:g}) must lie inside the spec's {spec}"
                )
            resolved[name] = (lo, hi)
        return resolved

    def sample(
        self,
        voice: Voice,
        rng: np.random.Generator,
        bounds: Mapping[str, tuple[float, float]],
        paths: Mapping[str, str] | None = None,
    ) -> dict | None:
        """Random valid parameters for this source, uniform within `bounds` (from
        `resolve_bounds`); None if the source has no syllable the family can target. `paths` gives
        the values of the family's optional path parameters (e.g. `noise_wav`); the others stay
        unset."""
        p: dict = {}
        if self.indexed:
            options = self.syllables(voice)
            if not options:
                return None
            p["index"] = int(rng.choice(options))
        if self.takes_to:
            tones = self.choices(voice, p["index"])
            if not tones:
                return None
            p["to"] = str(rng.choice(tones))
        for name, spec in self.bounds.items():
            lo, hi = bounds[name]
            x = float(rng.uniform(lo, hi))
            if spec.signed and rng.random() < 0.5:
                x = -x
            p[name] = _tidy(x, lo, hi, spec.signed)
        for name in self.optional_paths:
            if paths and name in paths:
                p[name] = paths[name]
        return p


def _tidy(x: float, lo: float, hi: float, signed: bool) -> float:
    """`x` rounded to three decimals and kept inside `lo..hi`; for a signed parameter (whose
    bounds are on the magnitude) that is the magnitude, and the sign is kept."""
    if signed:
        magnitude = min(max(round(abs(x), 3), lo), hi)
        return magnitude if x >= 0 else -magnitude
    return min(max(round(x, 3), lo), hi)
