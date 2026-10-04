"""The corpus a session goes into, with the session's speaker added, or (for purge) taken out
(docs/s05/contracts.md section 3). Every result is validated by `parse_corpus`, so what is
written always loads."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..contracts.bundle import Session
from ..contracts.registry import (
    CorpusFile,
    RegistryError,
    Speaker,
    corpus_file_path,
    default_split,
    load_corpus_file,
    parse_corpus,
    volunteer_speaker_id,
)
from .errors import IntakeError

DEFAULT_SOURCE = "volunteer-corpus"


def _parsed(data: dict, pack: Path, source: str) -> CorpusFile:
    try:
        return parse_corpus(data, pack=pack, source=source)
    except RegistryError as e:
        raise IntakeError(str(e)) from e


def _check_source(source: str, register: Mapping[str, str]) -> None:
    if source not in register:
        raise IntakeError(f"source {source!r} is not an id in data-register.csv; add it there or pass --source")


def existing_or_new(
    root: Path, corpus_id: str, *, lect: str, pack: Path, source: str | None, register: Mapping[str, str]
) -> tuple[CorpusFile, bool]:
    """The corpus `corpus_id` and whether it is new. A new corpus is `recorded`, of the deck's
    lect, with `source` (default volunteer-corpus); an existing one must be a recorded corpus of
    that lect, and `source`, if given, must be its source. The source must be in the register."""
    path = corpus_file_path(root, corpus_id)
    if not path.exists():
        chosen = source or DEFAULT_SOURCE
        _check_source(chosen, register)
        meta = {"id": corpus_id, "source": chosen, "kind": "recorded", "lect": lect}
        return _parsed({"corpus": meta}, pack, f"corpus {corpus_id!r}"), True
    try:
        corpus = load_corpus_file(path, pack=pack)
    except RegistryError as e:
        raise IntakeError(str(e)) from e
    meta = corpus.corpus
    if meta.kind != "recorded":
        raise IntakeError(f"{path}: corpus {corpus_id!r} is {meta.kind}; kit sessions go into a recorded corpus")
    if meta.lect != lect:
        raise IntakeError(f"{path}: corpus {corpus_id!r} is lect {meta.lect!r} but the deck is {lect!r}")
    if source is not None and source != meta.source:
        raise IntakeError(f"{path}: corpus {corpus_id!r} has source {meta.source!r}, not --source {source!r}")
    _check_source(meta.source, register)
    return corpus, False


def session_speaker(session: Session) -> Speaker:
    """`v-<code>`, from the session's answers (prefer_not included), split `gate`, and no stored
    accent: graders use the default for `grew_up_hearing` (R82)."""
    sid = volunteer_speaker_id(session.session)
    return Speaker(
        id=sid,
        background=session.speaker.background,
        grew_up_hearing=session.speaker.grew_up_hearing,
        split=default_split("recorded", sid),
        sessions=[session.session],
    )


def with_speaker(corpus: CorpusFile, speaker: Speaker, pack: Path) -> CorpusFile:
    data = corpus.model_dump(exclude_none=True)
    data["speaker"].append(speaker.model_dump(exclude_none=True))
    return _parsed(data, pack, f"corpus {corpus.corpus.id!r}")


def without_session(corpus: CorpusFile, code: str, pack: Path) -> CorpusFile:
    """`corpus` without session `code`: a speaker whose only session it is goes, a speaker with
    other sessions keeps them."""
    data = corpus.model_dump(exclude_none=True)
    speakers = []
    for s in data["speaker"]:
        if code in s["sessions"]:
            s["sessions"] = [c for c in s["sessions"] if c != code]
            if not s["sessions"]:
                continue
        speakers.append(s)
    data["speaker"] = speakers
    return _parsed(data, pack, f"corpus {corpus.corpus.id!r}")
