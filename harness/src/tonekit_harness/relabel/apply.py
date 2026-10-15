"""`tkh relabel`'s writes, in an order an interruption cannot hurt: the new manifest is written
beside the old one and checked as `tkh eval` reads it; then the log gets its entries (each row
change keeps the row before it, so the row intake wrote is never lost); then the new manifest
replaces the old one in one rename; then the corpus is marked stale. A run cut short after the log
is finished by running it again: the plan is made from the rows, not from the log."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .. import manifest
from ..contracts.pack import load_pack_info
from ..contracts.relabel import LogEntry, RelabelError, RelabelExport
from ..intake import layout
from ..intake.manifest_lines import appended, rewritten
from ..intake.packs import pack_path
from ..manifest import ManifestError
from ..registry.stale import mark_stale
from .plan import Plan, plan_relabel
from .state import CorpusState, corpus_state, session_of


@dataclass(frozen=True)
class Outcome:
    state: CorpusState  # the corpus before
    plan: Plan
    log: Path
    stale: Path | None  # the stale marker, when rows changed


def _new_text(state: CorpusState, plan: Plan) -> str:
    """The manifest with the changed rows replaced or removed in place, and rows excluded before
    and now back appended at the end."""
    in_place = {
        cid: None if ch.after is None else ch.after.model_dump_json()
        for cid, ch in plan.changes.items()
        if ch.before is not None
    }
    back = [ch.after.model_dump_json() for ch in plan.changes.values() if ch.before is None and ch.after is not None]
    text = rewritten(state.text, in_place)
    return appended(text, back) if back else text


def _staged(state: CorpusState, text: str, register: Mapping[str, str]) -> Path:
    """The new manifest, written beside the old one and loaded as `tkh eval` loads it."""
    for leftover in layout.relabel_temps(state.corpus):  # from a relabel that was killed
        leftover.unlink()
    tmp = layout.relabel_temp(state.manifest)
    tmp.write_text(text, encoding="utf-8")
    try:
        ids = [c.id for c in manifest.load(tmp, register=register)]
        if len(ids) != len(set(ids)):
            raise RelabelError("the relabelled manifest would repeat a clip id (nothing written)")
    except (ManifestError, RelabelError) as e:
        tmp.unlink()
        raise RelabelError(f"the relabelled manifest would not load (nothing written): {e}") from e
    return tmp


def _entries(plan: Plan, now: datetime) -> list[LogEntry]:
    clips = list(dict.fromkeys([*plan.new, *plan.changes]))
    return [
        LogEntry(
            session=session_of(cid), clip=cid, applied_at=now, decision=plan.new.get(cid), row=plan.changes.get(cid)
        )
        for cid in clips
    ]


def _append_log(path: Path, entries: list[LogEntry]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write("".join(e.model_dump_json() + "\n" for e in entries))
        f.flush()
        os.fsync(f.fileno())


def relabel_corpus(
    root: Path,
    corpus_id: str,
    export: RelabelExport,
    *,
    repo: Path,
    register: Mapping[str, str],
    source: str,
    now: datetime | None = None,
) -> Outcome:
    """Apply `export` (read from `source`, a name for the stale reason) to the corpus. Raises
    `RelabelError` with nothing written when the file does not fit the corpus."""
    state = corpus_state(root, corpus_id)
    try:
        tone_ids = load_pack_info(pack_path(repo, state.lect)).tone_ids
    except ValueError as e:
        raise RelabelError(str(e)) from e
    plan = plan_relabel(state, export, tone_ids)
    at = now or datetime.now(UTC)
    if plan.nothing:
        return Outcome(state, plan, state.log, None)
    tmp = _staged(state, _new_text(state, plan), register) if plan.changes else None
    try:
        _append_log(state.log, _entries(plan, at))
        if tmp is not None:
            os.replace(tmp, state.manifest)
    except BaseException:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        raise
    if tmp is None:
        return Outcome(state, plan, state.log, None)
    n = len(plan.changes)
    stale = mark_stale(root, corpus_id, f"relabelled {n} clip{'s' if n != 1 else ''} ({source})", now=at)
    return Outcome(state, plan, state.log, stale)
