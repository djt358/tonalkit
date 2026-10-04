"""Where a session's data is under the data root: in which corpora (a speaker entry, manifest
rows, its audio, its session.json copy) and in which staging areas a killed intake left behind.
Intake refuses a session found anywhere; purge removes what this finds."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..contracts.registry import corpus_dir, corpus_file_path
from ..contracts.relpath import is_relative_inside
from . import layout
from .errors import IntakeError
from .manifest_lines import without_rows

DEFAULT_MANIFEST = "manifest.jsonl"


@dataclass(frozen=True)
class CorpusTrace:
    corpus_id: str
    corpus: Path  # the corpus directory
    manifest: Path
    speakers: tuple[str, ...]  # corpus.toml speakers that list the session
    rows: int  # manifest rows of the session
    audio: bool  # its audio directory exists
    session_copy: bool  # its session.json copy exists

    def summary(self) -> str:
        parts = [f"speaker {s}" for s in self.speakers]
        if self.rows:
            parts.append(f"{self.rows} manifest row{'s' if self.rows != 1 else ''}")
        if self.audio:
            parts.append("audio")
        if self.session_copy:
            parts.append("session.json copy")
        return ", ".join(parts)


@dataclass(frozen=True)
class SessionTrace:
    code: str
    corpora: tuple[CorpusTrace, ...]
    staging: tuple[Path, ...]  # leftover staging areas

    @property
    def found(self) -> bool:
        return bool(self.corpora or self.staging)


def corpus_document(root: Path, corpus_id: str) -> dict:
    """The corpus.toml as parsed TOML ({} when there is none). Raises `IntakeError` when it cannot
    be read: neither intake nor purge guesses at a corpus file it cannot parse."""
    path = corpus_file_path(root, corpus_id)
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise IntakeError(f"{path}: cannot read the corpus file: {e}; fix it, then run again") from e


def manifest_path(root: Path, corpus_id: str, doc: dict) -> Path:
    name = (doc.get("corpus") or {}).get("manifest", DEFAULT_MANIFEST)
    if not isinstance(name, str) or not is_relative_inside(name):
        name = DEFAULT_MANIFEST
    return corpus_dir(root, corpus_id) / name


def _speakers(doc: dict, code: str) -> tuple[str, ...]:
    return tuple(
        str(s.get("id"))
        for s in doc.get("speaker") or []
        if isinstance(s, dict) and code in (s.get("sessions") or [])
    )


def manifest_text(manifest: Path) -> str:
    """The manifest's text ("" when there is none); raises `IntakeError` when it is not UTF-8."""
    if not manifest.is_file():
        return ""
    try:
        return manifest.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise IntakeError(f"{manifest}: not UTF-8 text ({e}); fix it, then run again") from e


def _rows(corpus: Path, manifest: Path, code: str) -> int:
    text = manifest_text(manifest)
    return without_rows(text, lambda row: layout.is_session_row(row, corpus, manifest, code))[1]


def trace_corpus(root: Path, corpus_id: str, code: str) -> CorpusTrace | None:
    """What of `code` is in one corpus, or None if nothing is."""
    doc = corpus_document(root, corpus_id)
    corpus = corpus_dir(root, corpus_id)
    manifest = manifest_path(root, corpus_id, doc)
    trace = CorpusTrace(
        corpus_id=corpus_id,
        corpus=corpus,
        manifest=manifest,
        speakers=_speakers(doc, code),
        rows=_rows(corpus, manifest, code),
        audio=layout.audio_dir(corpus, code).exists(),
        session_copy=layout.session_copy(corpus, code).exists(),
    )
    found = trace.speakers or trace.rows or trace.audio or trace.session_copy
    return trace if found else None


def find_session(root: Path, code: str) -> SessionTrace:
    """Every place under the data root that holds something of session `code`."""
    corpora = [t for cid in layout.corpus_ids(root) if (t := trace_corpus(root, cid, code)) is not None]
    return SessionTrace(code=code, corpora=tuple(corpora), staging=tuple(layout.staging_dirs(root, code)))
