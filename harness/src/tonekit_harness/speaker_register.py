"""Registers from a speaker's other speech (ruling R107): each clip graded with the register of
everything else that speaker said in the corpus, as Bendy's register stands once it has heard a
speaker for a while, rather than with the register of the 妈麻马骂 drill alone (R46).

A speaker can read a drill in another key than their phrases (several semitones lower, say),
and a register learnt from the drill alone then puts every tone of their phrases a Chao step too
high."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence

import numpy as np

from .manifest import Clip

MIN_REGISTER_ST = 4.0  # tonekit's minimum register width, expanded symmetrically


def register_bounds(voiced_st: np.ndarray) -> tuple[float, float]:
    """The speaker's register as (floor, ceil) semitones: p5 and p95 of the voiced semitones, at
    least `MIN_REGISTER_ST` wide (expanded symmetrically), Chao 1 and Chao 5."""
    floor, ceil = (float(x) for x in np.percentile(voiced_st, [5, 95]))
    if ceil - floor < MIN_REGISTER_ST:
        mid = (floor + ceil) / 2.0
        floor, ceil = mid - MIN_REGISTER_ST / 2.0, mid + MIN_REGISTER_ST / 2.0
    return floor, ceil


def pooled_register(voiced_st: Sequence[float], syllables: int) -> dict | None:
    """A warm register over `voiced_st` (`register_bounds`, and the median), counting
    `syllables`, as register JSON. None without a finite value."""
    v = np.array([x for x in voiced_st if np.isfinite(x)], dtype=float)
    if v.size == 0:
        return None
    floor, ceil = register_bounds(v)
    median = float(np.median(v))
    return {"floor_st": floor, "median_st": median, "ceil_st": ceil, "n_syllables": int(syllables)}


def leave_one_out_registers(
    clips: Sequence[Clip], analysis_of: Callable[[Clip], dict]
) -> dict[str, str | None]:
    """Clip id -> the register JSON of the same speaker's other clips (`pooled_register` over
    their voiced semitones, counting their nuclei as syllables). `analysis_of` gives a clip's
    Analysis (any register: the voiced semitones do not depend on it). None for a speaker's only
    clip, or when the others have no voiced frame."""
    seen = {c.id: analysis_of(c) for c in clips}
    out: dict[str, str | None] = {}
    for clip in clips:
        others = [seen[c.id] for c in clips if c.speaker == clip.speaker and c.id != clip.id]
        st = [x for a in others for x in a["voiced_st"]]
        register = pooled_register(st, sum(len(a["nuclei"]) for a in others))
        out[clip.id] = None if register is None else json.dumps(register, sort_keys=True, separators=(",", ":"))
    return out
