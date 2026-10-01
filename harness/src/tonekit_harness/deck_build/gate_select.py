"""Choosing the gate pairs from the rows that can make one. The gate must cover the sandhi cases
of 一 before a measure word: the quota is how many pairs have each tone after 一 (yì before 1, 2
and 3, yí before 4), and one pair in ten (two of twenty) must have a run of third tones
inside the phrase (一碗水 is yì wán shuǐ). No measure word is used more than twice."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .error_word import Substitution
from .reading import Reading

TONE_SHARES = {"1": 5, "2": 4, "3": 5, "4": 6}  # of 20
T3_RUNS_PER_TEN = 1  # pairs, per ten, that have a run of third tones inside the phrase
MAX_PER_MEASURE = 2


@dataclass(frozen=True)
class Usable:
    where: str
    reading: Reading
    substitution: Substitution
    flag: str
    status: str

    @property
    def after_yi(self) -> str:
        """The citation tone of the syllable after 一, which decides yì or yí."""
        return self.reading.citation()[1].tone

    @property
    def has_t3_run(self) -> bool:
        tones = [s.tone for s in self.reading.citation()]
        return any(a == b == "3" for a, b in zip(tones, tones[1:], strict=False))

    @property
    def measure(self) -> str:
        return self.reading.text[1]


@dataclass(frozen=True)
class Left:
    """A source row that did not become a pair, and why."""

    where: str
    text: str
    reason: str


def quotas(n: int) -> dict[str, int]:
    """TONE_SHARES scaled to n pairs (largest remainder; 20 gives the shares themselves)."""
    total = sum(TONE_SHARES.values())
    exact = {t: n * s / total for t, s in TONE_SHARES.items()}
    out = {t: int(x) for t, x in exact.items()}
    by_remainder = sorted(exact, key=lambda t: (exact[t] - out[t], t), reverse=True)
    for t in by_remainder[: n - sum(out.values())]:
        out[t] += 1
    return out


def select(usable: Sequence[Usable], n: int) -> tuple[list[Usable], list[Left]]:
    """Up to `n` rows, in their file order, and the rows passed over with the reason."""
    chosen: list[Usable] = []
    per_measure: dict[str, int] = {}
    per_tone: dict[str, int] = {}

    def take(u: Usable) -> None:
        chosen.append(u)
        per_measure[u.measure] = per_measure.get(u.measure, 0) + 1
        per_tone[u.after_yi] = per_tone.get(u.after_yi, 0) + 1

    def free(u: Usable) -> bool:
        return u not in chosen and len(chosen) < n and per_measure.get(u.measure, 0) < MAX_PER_MEASURE

    for u in usable:  # a run of third tones inside the phrase
        if sum(c.has_t3_run for c in chosen) < n * T3_RUNS_PER_TEN // 10 and u.has_t3_run and free(u):
            take(u)
    for tone, quota in quotas(n).items():  # each tone after 一
        for u in usable:
            if u.after_yi == tone and per_tone.get(tone, 0) < quota and free(u):
                take(u)
    for u in usable:  # anything, if a tone ran short
        if free(u):
            take(u)
    passed_over = [Left(u.where, u.reading.text, _why(u, per_measure, n)) for u in usable if u not in chosen]
    return [u for u in usable if u in chosen], passed_over


def _why(u: Usable, per_measure: dict[str, int], n: int) -> str:
    if per_measure.get(u.measure, 0) >= MAX_PER_MEASURE:
        return f"not needed: {u.measure} is already in {MAX_PER_MEASURE} pairs"
    return f"not needed: {n} pairs are chosen and the tone after 一 ({u.after_yi}) is covered"
