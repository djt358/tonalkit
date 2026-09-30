"""What a family needs to know about a source clip: the pack's tones, the reading, where each
syllable's voiced core is, the f0 and the speaker's register (`Voice`), and `render`, which
redraws one syllable along Chao knots. Pure: no audio, no I/O."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from .family import SynthError

HOP_MS = 10.0  # one frame, in milliseconds

# The neutral tone has no citation contour of its own (cmn.toml gives it `chao = "context"`), but
# to shift the onset or offset of a neutral syllable the harness has to draw one: a short fall, as
# in tests/support.py. Keyed by the pack's language and tone id. It is only a syllable's own
# contour; no family uses a context tone as the target `to` of a swap.
CONTEXT_FALLBACK: dict[tuple[str, str], tuple[float, ...]] = {("cmn", "5"): (3.0, 2.0)}

# A dipping tone produced without its dip: (language, tone) -> (the tone it is heard as, Chao
# knots). The low rise [2, 4] is what listeners hear as a T2, the classic T3 error.
NO_DIP: dict[tuple[str, str], tuple[str, tuple[float, ...]]] = {("cmn", "3"): ("2", (2.0, 4.0))}

# A turn-point shift may not push its knot closer than this (fraction of the syllable) to a
# neighbouring knot or to the syllable's edge.
KNOT_MARGIN = 0.1


@dataclass(frozen=True)
class PackTones:
    """The pack's tones: `chao` maps a tone id to its Chao knots, or None for a context tone."""

    lect: str
    chao: Mapping[str, tuple[float, ...] | None]

    @classmethod
    def parse(cls, pack_toml: str) -> PackTones:
        try:
            pack = tomllib.loads(pack_toml)
        except tomllib.TOMLDecodeError as e:
            raise SynthError(f"the pack is not valid TOML: {e}") from e
        lect = pack.get("pack", {}).get("lect")
        chao: dict[str, tuple[float, ...] | None] = {}
        for tone in pack.get("tone", []):
            knots = tone.get("chao")
            chao[tone["id"]] = tuple(float(k) for k in knots) if isinstance(knots, list) else None
        if not isinstance(lect, str) or not chao:
            raise SynthError("the pack needs a [pack] lect and at least one [[tone]]")
        return cls(lect, chao)

    def is_context(self, tone: str) -> bool:
        """True for a tone whose contour depends on context (no fixed citation form)."""
        return self.chao[tone] is None

    def citable(self) -> list[str]:
        """The tones with a fixed citation contour, in pack order."""
        return [t for t, knots in self.chao.items() if knots is not None]

    def has_contour(self, tone: str) -> bool:
        return not self.is_context(tone) or (self.lect, tone) in CONTEXT_FALLBACK

    def contour(self, tone: str) -> tuple[float, ...]:
        """The Chao knots that draw `tone`: its citation form, or the context fallback."""
        knots = self.chao[tone]
        if knots is None:
            knots = CONTEXT_FALLBACK.get((self.lect, tone))
        if knots is None:
            raise SynthError(f"tone {tone!r} has no contour to draw (context tone, no fallback)")
        return knots


@dataclass(frozen=True)
class Voice:
    """One source clip as the families see it: the reading, where each syllable's voiced core is,
    the f0 and the speaker's register. No audio."""

    tones: tuple[str, ...]  # the intended reading
    extents: tuple[tuple[int, int] | None, ...]  # per syllable: voiced frames [start, end), or None
    st: np.ndarray  # source f0 in semitones re 55 Hz per 10 ms frame; NaN where unvoiced
    floor: float  # the register, in semitones: Chao 1 ...
    ceil: float  # ... and Chao 5
    pack: PackTones

    def targetable(self) -> list[int]:
        return [i for i, extent in enumerate(self.extents) if extent is not None]


def substitute(tones: Sequence[str], index: int, tone: str) -> list[str]:
    out = list(tones)
    out[index] = tone
    return out


def render(
    voice: Voice, index: int, knots: Sequence[float], times: Sequence[float] | None = None
) -> np.ndarray:
    """The source f0 with syllable `index` redrawn along Chao `knots`, in the source's register.

    Knots sit at `times` (default: evenly spaced) over the syllable's voiced core and are joined
    linearly; a Chao value c is `floor + (c - 1) / 4 * (ceil - floor)` semitones. Only frames that
    are voiced in the source get the new f0. The two frames on each side of the core are blended
    linearly (in semitones) toward the new contour's end values, so the join does not click.
    """
    start, end = voice.extents[index]  # type: ignore[misc]  # `index` is a validated syllable
    chao = np.asarray(knots, dtype=float)
    knots_st = voice.floor + (chao - 1.0) / 4.0 * (voice.ceil - voice.floor)
    if times is None:
        times = np.linspace(0.0, 1.0, len(knots))
    contour = np.interp(np.linspace(0.0, 1.0, end - start), times, knots_st)

    out = voice.st.copy()
    core = out[start:end]  # a view
    voiced = ~np.isnan(core)
    core[voiced] = contour[voiced]
    for k in (1, 2):
        w = 1.0 - k / 3.0  # weight of the new contour: 2/3, then 1/3
        for i, edge in ((start - k, contour[0]), (end - 1 + k, contour[-1])):
            if 0 <= i < len(out) and not np.isnan(out[i]):
                out[i] = w * edge + (1.0 - w) * out[i]
    return out
