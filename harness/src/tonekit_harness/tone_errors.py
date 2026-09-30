"""The `tone_error` families: the syllable is spoken with a different tone."""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from .family import Family
from .voice import NO_DIP, Voice, render, substitute


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
