"""`tkh purge --session CODE` (docs/s05/contracts.md section 6): remove everything intake wrote
for a session, its bundles in inbox/ and the analysis cache, mark the corpora it changed stale,
and log it. What would be written is worked out and checked before anything is deleted; a code
found nowhere changes nothing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..atomic import write_text_atomic
from ..contracts.registry import PurgeRecord, RegistryError, corpus_file_path, inbox_dir, load_corpus_file
from . import layout
from .analysis_cache import clear_analysis_cache
from .bundle_match import session_bundles
from .commit import remove_tree
from .corpus_toml import corpus_toml_text
from .corpus_update import without_session
from .errors import IntakeError
from .manifest_lines import without_rows
from .packs import pack_path
from .purge_log import append_purge_record
from .stale import mark_stale
from .trace import CorpusTrace, corpus_document, find_session, manifest_text


@dataclass(frozen=True)
class CorpusPlan:
    trace: CorpusTrace
    corpus_text: str | None  # corpus.toml without the session; None: leave it
    manifest_text: str | None  # the manifest without the session's rows; None: leave it


@dataclass(frozen=True)
class PurgeOutcome:
    record: PurgeRecord
    corpora: tuple[CorpusTrace, ...]
    staging: int  # leftover staging areas removed
    inbox: int  # bundles removed from inbox/
    cache_entries: int  # analysis-cache files cleared
    log: Path


def _corpus_text(root: Path, trace: CorpusTrace, code: str, repo: Path) -> str | None:
    if not trace.speakers:
        return None
    path = corpus_file_path(root, trace.corpus_id)
    lect = (corpus_document(root, trace.corpus_id).get("corpus") or {}).get("lect", "")
    pack = pack_path(repo, str(lect))
    try:
        corpus = load_corpus_file(path, pack=pack)
    except RegistryError as e:
        raise IntakeError(f"{e}\nfix the corpus file, then purge again (nothing was removed)") from e
    return corpus_toml_text(without_session(corpus, code, pack))


def _manifest_text(trace: CorpusTrace, code: str) -> str | None:
    if not trace.rows:
        return None
    text = manifest_text(trace.manifest)
    return without_rows(text, lambda row: layout.is_session_row(row, trace.corpus, trace.manifest, code))[0]


def _plan(root: Path, trace: CorpusTrace, code: str, repo: Path) -> CorpusPlan:
    return CorpusPlan(trace, _corpus_text(root, trace, code, repo), _manifest_text(trace, code))


def _remove_if_empty(d: Path) -> None:
    if d.is_dir() and not any(d.iterdir()):
        d.rmdir()


def _apply(root: Path, plan: CorpusPlan, code: str) -> int:
    """Rewrite the manifest and corpus.toml, then delete the session's files; returns how many."""
    t = plan.trace
    if plan.manifest_text is not None:
        write_text_atomic(t.manifest, plan.manifest_text)
    if plan.corpus_text is not None:
        write_text_atomic(corpus_file_path(root, t.corpus_id), plan.corpus_text)
    removed = 0
    for path in (layout.audio_dir(t.corpus, code), layout.session_copy(t.corpus, code)):
        if path.exists():
            removed += remove_tree(path)
            _remove_if_empty(path.parent)
    return removed


def purge_session(
    root: Path, code: str, *, repo: Path, cache_dir: Path, now: datetime | None = None
) -> PurgeOutcome | None:
    """Purge session `code` under the data root `root`; None when nothing of it was found (and
    nothing changed). `cache_dir` is `tkh eval`'s analysis cache."""
    trace = find_session(root, code)
    inbox = session_bundles(inbox_dir(root), code)
    if not trace.found and not inbox:
        return None
    plans = [_plan(root, t, code, repo) for t in trace.corpora]  # may refuse: before any change
    files = sum(_apply(root, p, code) for p in plans)
    files += sum(remove_tree(d) for d in trace.staging)
    files += sum(remove_tree(p) for p in inbox)
    cache = clear_analysis_cache(cache_dir) if trace.corpora else 0
    at = now or datetime.now(UTC)
    for t in trace.corpora:
        mark_stale(root, t.corpus_id, f"purged session {code}", now=at)
    record = PurgeRecord(
        session=code, purged_at=at, files_removed=files, corpora=[t.corpus_id for t in trace.corpora]
    )
    log = append_purge_record(root, record)
    return PurgeOutcome(
        record=record, corpora=trace.corpora, staging=len(trace.staging), inbox=len(inbox), cache_entries=cache, log=log
    )
