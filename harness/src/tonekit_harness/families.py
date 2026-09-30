"""The registry of perturbation families (spec §9): `FAMILIES`, lookup, and the helpers `tkh synth`
and the adversary use to sample from them. The families themselves are in `tone_errors`, `graded`
and `nuisance`, on the base in `family` and the source description in `voice`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from .family import Bound, Family, SynthError
from .graded import OffsetShift, OnsetShift, RangeCompress, TurnShift
from .nuisance import Identity, Noise, Rate, RegisterShift
from .tone_errors import NeutralFull, T3NoDip, ToneSwap
from .voice import PackTones, Voice

__all__ = [
    "FAMILIES",
    "Bound",
    "Family",
    "PackTones",
    "SynthError",
    "Voice",
    "draw",
    "get",
    "resolve_pool_bounds",
    "searched",
]

FAMILIES: dict[str, Family] = {
    f.name: f
    for f in (
        Identity(),
        ToneSwap(),
        T3NoDip(),
        NeutralFull(),
        RangeCompress(),
        TurnShift(),
        OnsetShift(),
        OffsetShift(),
        Noise(),
        RegisterShift(),
        Rate(),
    )
}


def get(name: str) -> Family:
    try:
        return FAMILIES[name]
    except KeyError:
        raise SynthError(f"unknown family {name!r}; known: {', '.join(FAMILIES)}") from None


def searched(labels: Sequence[str]) -> list[Family]:
    """The families `tkh synth` and the adversary sample from, restricted to `labels`."""
    return [f for f in FAMILIES.values() if f.searchable and f.label in labels]


def resolve_pool_bounds(
    pool: Sequence[Family], overrides: Mapping[str, Mapping[str, tuple[float, float]]] | None
) -> dict[str, dict[str, tuple[float, float]]]:
    """Each family in `pool`'s sampling bounds: the spec's, or the caller's `overrides` (which must
    lie inside them and may only name families in `pool`)."""
    overrides = overrides or {}
    for name in overrides:
        family = get(name)
        if family not in pool:
            raise SynthError(f"{name}: not searched, so it takes no bounds")
    return {f.name: f.resolve_bounds(overrides.get(f.name)) for f in pool}


def draw(
    voice: Voice,
    rng: np.random.Generator,
    pool: Sequence[Family],
    bounds: Mapping[str, Mapping[str, tuple[float, float]]],
    paths: Mapping[str, str] | None = None,
) -> tuple[Family, dict]:
    """A random family from `pool` that can perturb `voice`, with random valid parameters within
    `bounds` (from `resolve_pool_bounds`); `paths` gives the optional file parameters (see
    `Family.sample`).

    The class (`Family.label`) is chosen first, each class in `pool` equally likely, then a family
    within it, each applicable one equally likely. A source that few families of a class apply to
    (a tone error needs a T3 to flatten or a neutral tone to fill out) is therefore perturbed by
    that class as often as by any other. A class with no family that applies to `voice` is
    skipped."""
    labels = list(dict.fromkeys(f.label for f in pool))
    for i in rng.permutation(len(labels)):
        members = [f for f in pool if f.label == labels[int(i)]]
        for j in rng.permutation(len(members)):
            family = members[int(j)]
            params = family.sample(voice, rng, bounds[family.name], paths)
            if params is not None:
                return family, params
    raise SynthError("no family can perturb this source")
