"""What a relabel file changes in a corpus, worked out and checked before anything is written.

Each clip's row is rebuilt from the row intake wrote and the clip's latest decision (`rules`),
then pairs are kept whole (`pairs`). A decision replaces the one applied before for the same clip
unless it was made earlier than that one; a decision that says what the applied one says changes
nothing. So applying the same file twice changes nothing, a newer export replaces older decisions,
and an older file applied late cannot undo them."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from ..contracts.relabel import WITH_TONES, AppliedDecision, Decision, RelabelError, RelabelExport, RowChange
from ..manifest import Clip
from .pairs import half_pairs, with_pairs
from .rules import card_tones, relabelled
from .state import ClipState, CorpusState


@dataclass(frozen=True)
class Plan:
    new: dict[str, AppliedDecision]  # decisions to log: new, or saying something else than before
    older: list[str]  # clips whose decision here is older than the one applied: skipped
    unknown: list[str]  # clips the corpus does not have (a purged session?): skipped
    target: dict[str, Clip | None]  # every clip's row afterwards; None: excluded
    changes: dict[str, RowChange]  # the rows that change
    half_pairs: list[str]  # pairs whose clips leave the pair (R112)

    @property
    def nothing(self) -> bool:
        return not self.new and not self.changes


def _problems(d: Decision, st: ClipState, tone_ids: Collection[str]) -> list[str]:
    if d.verdict not in WITH_TONES or d.tones is None:
        return []
    n = len(st.original.intended.tones)
    problems = []
    if len(d.tones) != n:
        problems.append(f"{d.clip}: {len(d.tones)} tones for a reading of {n} syllables")
    unknown = sorted(set(d.tones) - set(tone_ids))
    if unknown:
        problems.append(f"{d.clip}: tones {', '.join(unknown)} are not tone ids of the pack")
    if d.verdict == "as_card" and d.tones != card_tones(st.original):
        problems.append(
            f"{d.clip}: 'as the card says' with tones {' '.join(d.tones)}, but the card asks for "
            f"{' '.join(card_tones(st.original))}"
        )
    return problems


def _normalised(d: Decision, st: ClipState, who: str) -> AppliedDecision:
    """As the log keeps it: the tones of `heard` only, and `heard` the card's tones is `as_card`."""
    as_card = d.verdict == "as_card" or (d.verdict == "heard" and d.tones == card_tones(st.original))
    if as_card:
        return AppliedDecision(verdict="as_card", tones=None, decided_at=d.decided_at, who=who)
    return AppliedDecision(verdict=d.verdict, tones=d.tones, decided_at=d.decided_at, who=who)


def plan_relabel(state: CorpusState, export: RelabelExport, tone_ids: Collection[str]) -> Plan:
    """The relabel of `state` by `export`. Raises `RelabelError` (listing every problem) when the
    file is for another corpus or a decision does not fit its clip."""
    if export.corpus != state.corpus_id:
        raise RelabelError(f"the file is for corpus {export.corpus!r}, not {state.corpus_id!r}")
    known = [(d, state.clips[d.clip]) for d in export.decisions if d.clip in state.clips]
    problems = [p for d, st in known for p in _problems(d, st, tone_ids)]
    if problems:
        raise RelabelError("decisions that do not fit their clips (nothing written):\n  " + "\n  ".join(problems))
    new: dict[str, AppliedDecision] = {}
    older = []
    for d, st in known:
        decision = _normalised(d, st, export.who)
        if st.applied is not None and decision.decided_at < st.applied.decided_at:
            older.append(d.clip)
        elif st.applied is None or not st.applied.same_verdict(decision):
            new[d.clip] = decision
    rebuilt = {cid: relabelled(st.original, new[cid] if cid in new else st.applied) for cid, st in state.clips.items()}
    target = with_pairs(rebuilt, state.originals)
    changes = {
        cid: RowChange(before=st.current, after=target[cid])
        for cid, st in state.clips.items()
        if target[cid] != st.current
    }
    return Plan(
        new=new,
        older=older,
        unknown=[d.clip for d in export.decisions if d.clip not in state.clips],
        target=target,
        changes=changes,
        half_pairs=half_pairs(rebuilt, state.originals),
    )
