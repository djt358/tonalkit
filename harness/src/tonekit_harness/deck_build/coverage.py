"""Whether the chosen gate pairs cover the sandhi cases of 一 (the quotas of `gate_select`): how many
pairs have each tone after 一, and how many have a run of third tones. A short quota of yí (a
fourth tone after 一) or of third-tone runs fails the build, because the gate would not test what
it is for; a short quota of the other tones is only reported (anything may fill a short tone)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from .gate_select import Usable, quotas, t3_run_quota

YI_TONE = "4"  # a fourth tone after 一 makes it yí


@dataclass(frozen=True)
class Coverage:
    pairs: int  # the number of pairs asked for
    chosen: dict[str, int]  # tone after 一 -> pairs chosen
    quota: dict[str, int]  # tone after 一 -> pairs wanted
    t3_runs: int  # pairs with a run of third tones
    t3_quota: int

    def line(self) -> str:
        tones = ", ".join(
            f"{t}{' (yí)' if t == YI_TONE else ''}: {self.chosen.get(t, 0)}/{q}" for t, q in self.quota.items()
        )
        return f"gate coverage, chosen/quota: tone after 一 {tones}; third-tone runs: {self.t3_runs}/{self.t3_quota}"

    def problems(self) -> list[str]:
        problems = []
        if (got := self.chosen.get(YI_TONE, 0)) < self.quota[YI_TONE]:
            problems.append(
                f"only {got} of {self.quota[YI_TONE]} pairs have a fourth tone after 一 (yí); "
                f"add rows with a fourth-tone measure word"
            )
        if self.t3_runs < self.t3_quota:
            problems.append(
                f"only {self.t3_runs} of {self.t3_quota} pairs have a run of third tones in the phrase "
                "(一碗水 is yì wán shuǐ); add rows with a third-tone measure word and noun"
            )
        return problems


def coverage_of(chosen: Sequence[Usable], pairs: int) -> Coverage:
    return Coverage(
        pairs,
        dict(Counter(u.after_yi for u in chosen)),
        quotas(pairs),
        sum(u.has_t3_run for u in chosen),
        t3_run_quota(pairs),
    )
