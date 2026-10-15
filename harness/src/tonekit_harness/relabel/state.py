"""A corpus as relabel and the review page see it: per clip, the row intake wrote (the card's
reading), the row in the manifest now (None once excluded) and the latest decision applied. The
row intake wrote is the manifest's row until a relabel first changes it; from then on the log's
first change of that clip says what it was."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..contracts.bundle import SESSION_CODE_PATTERN
from ..contracts.registry import corpus_dir, corpus_file_path
from ..contracts.relabel import AppliedDecision, LogEntry, RelabelError, load_log
from ..intake import layout
from ..intake.trace import corpus_document, manifest_path, manifest_text
from ..manifest import Clip
from ..manifest import load as load_manifest

_CODE = re.compile(SESSION_CODE_PATTERN.removeprefix("^").removesuffix("$"))


@dataclass(frozen=True)
class ClipState:
    id: str
    original: Clip  # as intake wrote it: the card's reading
    current: Clip | None  # the manifest's row now; None: excluded
    applied: AppliedDecision | None  # the latest decision applied to it


@dataclass(frozen=True)
class CorpusState:
    corpus_id: str
    corpus: Path  # the corpus directory
    manifest: Path
    lect: str
    text: str  # the manifest as it is
    clips: dict[str, ClipState]  # manifest order, then clips excluded earlier in log order
    log: Path

    @property
    def originals(self) -> dict[str, Clip]:
        return {cid: c.original for cid, c in self.clips.items()}

    @property
    def current(self) -> dict[str, Clip | None]:
        return {cid: c.current for cid, c in self.clips.items()}


def session_of(clip_id: str) -> str | None:
    """The session code a volunteer clip id starts with (`<CODE>-<card>`), else None."""
    head = clip_id.split("-", 1)[0]
    return head if "-" in clip_id and _CODE.fullmatch(head) else None


def _originals(entries: list[LogEntry]) -> dict[str, Clip]:
    out: dict[str, Clip] = {}
    for e in entries:
        if e.row is not None and e.row.before is not None and e.clip not in out:
            out[e.clip] = e.row.before
    return out


def _applied(entries: list[LogEntry]) -> dict[str, AppliedDecision]:
    out: dict[str, AppliedDecision] = {}
    for e in entries:
        if e.decision is not None:
            out[e.clip] = e.decision
    return out


def corpus_state(root: Path, corpus_id: str) -> CorpusState:
    """Read the corpus `corpus_id` under the data root `root`, its manifest and its relabel log.
    Raises `RelabelError` when there is no such corpus, or a file cannot be read."""
    if not corpus_file_path(root, corpus_id).is_file():
        raise RelabelError(f"no corpus {corpus_id!r} under {root} (no {corpus_file_path(root, corpus_id)})")
    try:
        doc = corpus_document(root, corpus_id)
        path = manifest_path(root, corpus_id, doc)
        text = manifest_text(path)
        rows = load_manifest(path) if path.is_file() else []
    except (ValueError, OSError) as e:  # IntakeError and ManifestError are ValueErrors
        raise RelabelError(str(e)) from e
    corpus = corpus_dir(root, corpus_id)
    log = layout.relabel_log(corpus)
    entries = load_log(log)
    originals, applied = _originals(entries), _applied(entries)
    clips: dict[str, ClipState] = {}
    for row in rows:
        if row.id in clips:
            raise RelabelError(f"{path}: clip id {row.id!r} is in the manifest twice")
        clips[row.id] = ClipState(row.id, originals.get(row.id, row), row, applied.get(row.id))
    for cid, original in originals.items():
        if cid not in clips:  # excluded by an earlier relabel; its audio is still there
            clips[cid] = ClipState(cid, original, None, applied.get(cid))
    lect = str((doc.get("corpus") or {}).get("lect", ""))
    return CorpusState(corpus_id, corpus, path, lect, text, clips, log)

