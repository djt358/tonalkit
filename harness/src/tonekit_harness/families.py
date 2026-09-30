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
) -> tuple[Family, dict]:
    """A random family from `pool` that can perturb `voice` (each equally likely), with random
    valid parameters within `bounds` (from `resolve_pool_bounds`)."""
    for i in rng.permutation(len(pool)):
        family = pool[int(i)]
        params = family.sample(voice, rng, bounds[family.name])
        if params is not None:
            return family, params
    raise SynthError("no family can perturb this source")
