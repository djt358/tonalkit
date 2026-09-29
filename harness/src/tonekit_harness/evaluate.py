"""Grade every manifest clip with tonekit and collect one `Result` per clip."""

from __future__ import annotations

from dataclasses import dataclass, field

# A shape delta as (kind, amount): kind is a tonekit `DeltaKind` name such as "WiderRange";
# amount is in Chao units, or in ms for "TurnEarlier" and "TurnLater".
Delta = tuple[str, float]


@dataclass
class Syllable:
    """One syllable of the intended reading, from tonekit's `SyllableAssessment`."""

    expected: str
    heard: str | None
    p_correct: float
    distance: float | None
    measured: str  # "Full", "Partial" or "NotMeasured"
    deltas: list[Delta] = field(default_factory=list)


@dataclass
class Result:
    """How tonekit graded one clip."""

    id: str
    set: str
    pair: str | None
    label: str
    speaker: str
    overall: float | None  # None: no syllable was measured ("tone not checked")
    intended_rank: int  # 1: the intended reading beat every distractor
    margin_llr: float
    syllables: list[Syllable]
    register_source: str  # "cold" (estimated from this clip alone) or "given" (from register clips)
    issues: list[str] = field(default_factory=list)  # the analysis's signal issues, e.g. "LowSnr"
