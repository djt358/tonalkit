"""What `tkh eval` and `tkh fit` read when they are given `--select` instead of `--manifest`: the
selection under the data root, how to describe it in a report, and whether it may back a gate
verdict (`gate_clearance`)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path

from .. import clearance
from ..contracts.registry import Split
from .refusals import Refusal, RefusalError
from .root import DataRoot
from .selection import Selection
from .selectors import Selector, compose


def selection_from(
    selectors: Sequence[Selector],
    data: Path,
    pack: str | Path,
    *,
    default_splits: Sequence[Split] | None,
    speakers: Collection[str] | None = None,
) -> Selection:
    """The union of `selectors` under the data root `data`, the corpora's accents checked against
    `pack` (the pack the run grades with), keeping only `speakers` (qualified `corpus/speaker`
    ids) when given. Raises `SelectionError` or `RegistryError`."""
    selection = compose(DataRoot(data, pack=pack), selectors, default_splits=default_splits)
    return selection if not speakers else selection.of_speakers(speakers)


def describe(selection: Selection) -> str:
    """One line per corpus for a report: `aishell3 (public, aishell-3): 120 clips, 12 speakers`."""
    parts = []
    for corpus_id, meta in selection.corpora.items():
        mine = [i for i in selection.items if i.corpus.id == corpus_id]
        speakers = len({i.speaker.id for i in mine})
        splits = ", ".join(f"{s} {n}" for s, n in Counter(i.speaker.split for i in mine).items())
        parts.append(
            f"{corpus_id} ({meta.kind}, {meta.source}): {len(mine)} clips of {speakers} "
            f"speaker{'s' if speakers != 1 else ''} ({splits})"
        )
    return "; ".join(parts)


def accent_summary(accents: Mapping[str, str]) -> str:
    """`cmn-standard 10 speakers, cmn-TW 2 speakers`."""
    counts = Counter(accents.values())
    return ", ".join(f"{a} {n} speaker{'s' if n != 1 else ''}" for a, n in sorted(counts.items()))


def gate_clearance(
    selection: Selection, register: Mapping[str, str], *, allow_synthetic: bool = False
) -> tuple[clearance.Clearance, Refusal | None]:
    """What a run over `selection` may claim, and why not a verdict when it may not. The same as
    `clearance.assess` over its clips (which also refuses synthetic clips mixed with gate clips),
    and stricter: `Selection.for_gate` also refuses a corpus of kind `synthetic` and an empty
    selection. A refusal whose clips are all synthetic is a smoke run when `allow_synthetic`."""
    cleared = clearance.assess(selection.grading_clips(), register, allow_synthetic=allow_synthetic)
    try:
        selection.for_gate(register)
    except RefusalError as e:
        refusal = e.refusal
        mode = "smoke" if allow_synthetic and refusal.synthetic_only else "not a gate"
        return clearance.Clearance(mode, refusal.clips), refusal
    return cleared, None
