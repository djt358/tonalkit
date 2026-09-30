"""Pitch-tracking error rates against an f0 truth, per frame on tonekit's 10 ms grid.

A track is a `list[float | None]`: the pitch in Hz of each frame, `None` where it is unvoiced.

- **GPE** (gross pitch error): among the frames voiced in both the estimate and the truth, the
  fraction whose pitch is more than 20% off, `|est - truth| / truth > 0.2` (exactly 20% is not an
  error). `None` when no frame is voiced in both.
- **VDE** (voicing decision error): the fraction of all frames whose voicing differs.

`Counts` are the numerators and denominators, so clips pool frame by frame (`a + b`) rather than
as a mean of per-clip rates.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

GROSS_ERROR = 0.2  # a voiced frame is a gross error beyond this relative pitch error


@dataclass(frozen=True)
class Counts:
    frames: int = 0
    both_voiced: int = 0  # frames voiced in both the estimate and the truth
    gross_errors: int = 0  # of those, the ones more than 20% off
    voicing_errors: int = 0  # frames whose voicing differs

    def __add__(self, other: Counts) -> Counts:
        return Counts(
            self.frames + other.frames,
            self.both_voiced + other.both_voiced,
            self.gross_errors + other.gross_errors,
            self.voicing_errors + other.voicing_errors,
        )

    @property
    def gpe(self) -> float | None:
        return self.gross_errors / self.both_voiced if self.both_voiced else None

    @property
    def vde(self) -> float | None:
        return self.voicing_errors / self.frames if self.frames else None


def count(est: Sequence[float | None], truth: Sequence[float | None]) -> Counts:
    """The error counts of `est` against `truth`. Raises `ValueError` if their lengths differ."""
    if len(est) != len(truth):
        raise ValueError(
            f"the estimate has {len(est)} frames but the truth has {len(truth)} frames"
        )
    both = gross = differ = 0
    for e, t in zip(est, truth, strict=True):
        if (e is None) != (t is None):
            differ += 1
        elif e is not None and t is not None:
            both += 1
            gross += abs(e - t) / t > GROSS_ERROR
    return Counts(len(est), both, gross, differ)


def gpe(est: Sequence[float | None], truth: Sequence[float | None]) -> float | None:
    """Gross pitch error of `est` against `truth`; `None` if no frame is voiced in both."""
    return count(est, truth).gpe


def vde(est: Sequence[float | None], truth: Sequence[float | None]) -> float | None:
    """Voicing decision error of `est` against `truth`; `None` for no frames."""
    return count(est, truth).vde
