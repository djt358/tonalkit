"""The perturbation families of spec §9: registry, bounds and the pure transforms.

A family says which syllables it may target, which parameter values are allowed, and how it
changes what WORLD resynthesises: the f0 track (`contour`), the time base (`speed`) or the audio
(`audio`). There is no I/O here: `synth` runs the families over real clips.

- `tone_error` families change the tone the syllable carries: the label is `tone_error`.
- `graded` families keep the tone but distort it by a controlled amount: there is no binary truth.
- `correct` families are nuisance factors a listener would accept: the label is `correct`.

Magnitudes are spec §9's. Calling a family with a value outside them is a `SynthError`.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HOP_MS = 10.0

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


# ---- what a family needs to know about a source clip ------------------------------------------


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


def pink_noise(n: int, rng: np.random.Generator) -> np.ndarray:
    """Unit-RMS pink (1/f power) noise of `n` samples: white noise shaped in frequency."""
    spectrum = np.fft.rfft(rng.standard_normal(n))
    f = np.arange(len(spectrum), dtype=float)
    f[0] = 1.0
    spectrum /= np.sqrt(f)
    spectrum[0] = 0.0
    noise = np.fft.irfft(spectrum, n)
    return noise / np.sqrt(np.mean(noise**2))


# ---- families ---------------------------------------------------------------------------------


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
            if isinstance(index, bool) or not isinstance(index, int) or index not in ok:
                raise self._fail(
                    f"index {index!r} is not a syllable this family can target (targetable: {ok})"
                )
            out["index"] = index
        if self.takes_to:
            ok_tones = self.choices(voice, index)
            if params["to"] not in ok_tones:
                raise self._fail(f"to {params['to']!r} must be one of {ok_tones}")
            out["to"] = params["to"]
        for name, bound in self.bounds.items():
            x = params[name]
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not np.isfinite(x):
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
        self, voice: Voice, rng: np.random.Generator, bounds: Mapping[str, tuple[float, float]]
    ) -> dict | None:
        """Random valid parameters for this source, uniform within `bounds` (from
        `resolve_bounds`); None if the source has no syllable the family can target."""
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
            p[name] = _tidy(x, lo, hi)
        return p


def _tidy(x: float, lo: float, hi: float) -> float:
    """`x` rounded to three decimals, kept inside the magnitude range `lo..hi`."""
    magnitude = min(max(round(abs(x), 3), lo), hi)
    return magnitude if x >= 0 else -magnitude


class Identity(Family):
    """WORLD resynthesis of the source's own f0: the control every other family is compared with."""

    name = "identity"
    label = "correct"
    searchable = False


# -- tone_error --


class ToneSwap(Family):
    """A whole syllable spoken with another tone's citation contour."""

    name = "tone_swap"
    label = "tone_error"
    indexed = True
    takes_to = True

    def syllables(self, voice: Voice) -> list[int]:
        return [i for i in voice.targetable() if not voice.pack.is_context(voice.tones[i])]

    def choices(self, voice: Voice, index: int) -> list[str]:
        return [t for t in voice.pack.citable() if t != voice.tones[index]]

    def contour(self, voice: Voice, p: Mapping) -> np.ndarray:
        return render(voice, p["index"], voice.pack.contour(p["to"]))

    def produced(self, voice: Voice, p: Mapping) -> list[str]:
        return substitute(voice.tones, p["index"], p["to"])


class T3NoDip(Family):
    """A dipping tone spoken as a plain low rise."""

    name = "t3_no_dip"
    label = "tone_error"
    indexed = True

    def syllables(self, voice: Voice) -> list[int]:
        return [i for i in voice.targetable() if (voice.pack.lect, voice.tones[i]) in NO_DIP]

    def contour(self, voice: Voice, p: Mapping) -> np.ndarray:
        _, knots = NO_DIP[(voice.pack.lect, voice.tones[p["index"]])]
        return render(voice, p["index"], knots)

    def produced(self, voice: Voice, p: Mapping) -> list[str]:
        heard_as, _ = NO_DIP[(voice.pack.lect, voice.tones[p["index"]])]
        return substitute(voice.tones, p["index"], heard_as)


class NeutralFull(Family):
    """A neutral (context) syllable spoken with a full tone."""

    name = "neutral_full"
    label = "tone_error"
    indexed = True
    takes_to = True

    def syllables(self, voice: Voice) -> list[int]:
        return [i for i in voice.targetable() if voice.pack.is_context(voice.tones[i])]

    def choices(self, voice: Voice, index: int) -> list[str]:
        return voice.pack.citable()

    def contour(self, voice: Voice, p: Mapping) -> np.ndarray:
        return render(voice, p["index"], voice.pack.contour(p["to"]))

    def produced(self, voice: Voice, p: Mapping) -> list[str]:
        return substitute(voice.tones, p["index"], p["to"])


# -- graded --


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
    """The turning point (the middle knot of a tone with an interior knot) moved in time."""

    name = "turn_shift"
    bounds = {"ms": Bound(40.0, 120.0, signed=True)}

    def syllables(self, voice: Voice) -> list[int]:
        drawable = super().syllables(voice)
        return [i for i in drawable if len(voice.pack.contour(voice.tones[i])) >= 3]

    def contour(self, voice: Voice, p: Mapping) -> np.ndarray:
        knots = self.knots(voice, p)
        start, end = voice.extents[p["index"]]  # type: ignore[misc]
        times = np.linspace(0.0, 1.0, len(knots))
        j = len(knots) // 2
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


# -- correct (nuisance) --


class Noise(Family):
    """Noise added after resynthesis at `snr_db` relative to the speech power over voiced frames:
    seeded pink noise, or `noise_wav` (a 16 kHz mono recording, looped from a random start)."""

    name = "noise"
    label = "correct"
    bounds = {"snr_db": Bound(5.0, 20.0)}
    optional_paths = ("noise_wav",)

    def audio(self, y, voiced, p, rng, bed):
        if bed is None:
            noise = pink_noise(len(y), rng)
        else:
            if not np.any(bed):
                raise self._fail("the noise recording is silent")
            start = int(rng.integers(len(bed)))
            noise = np.resize(np.roll(bed, -start), len(y)).astype(np.float64)
            noise = noise / np.sqrt(np.mean(noise**2))
        speech = y[voiced] if voiced.any() else y
        speech_rms = np.sqrt(np.mean(speech.astype(np.float64) ** 2))
        return (y + speech_rms / 10.0 ** (p["snr_db"] / 20.0) * noise).astype(np.float32)

    def condition_noise(self, p: Mapping) -> str:
        kind = "pink" if p["noise_wav"] is None else Path(p["noise_wav"]).stem
        return f"{kind} {p['snr_db']:g} dB"


class RegisterShift(Family):
    """The whole f0 track moved up or down, `st` semitones."""

    name = "register_shift"
    label = "correct"
    bounds = {"st": Bound(-6.0, 6.0)}

    def contour(self, voice: Voice, p: Mapping) -> np.ndarray:
        return voice.st + p["st"]


class Rate(Family):
    """The whole utterance sped up (`factor` > 1: shorter) or slowed down."""

    name = "rate"
    label = "correct"
    bounds = {"factor": Bound(0.8, 1.25)}

    def speed(self, p: Mapping) -> float:
        return p["factor"]


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
