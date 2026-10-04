"""`tkh intake` for one bundle: read and check it, find its deck, build the rows and the speaker
entry, stage everything, check it, then move it into the corpus in one change. A refusal or a
failure leaves the data root as it was."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..contracts.bundle import Bundle, BundleError, read_bundle
from ..contracts.registry import Speaker, corpus_dir
from . import layout
from .checks import check_staged, manifest_ids
from .commit import MoveNew, Replace, apply_all, move_dir_into_place
from .corpus_toml import corpus_toml_text
from .corpus_update import existing_or_new, session_speaker, with_speaker
from .deck_lookup import find_deck
from .errors import IntakeError
from .manifest_lines import appended
from .packs import pack_path
from .rows import join_session
from .stage import Staged, clear_leftovers, stage
from .trace import find_session


@dataclass(frozen=True)
class IntakeOptions:
    root: Path  # the data root
    repo: Path  # the repository: decks, packs
    register: Mapping[str, str]  # data-register.csv: id -> shipped_weights_training
    corpus_id: str | None = None  # default: volunteers-<deck id>
    source: str | None = None  # a new corpus's source; default volunteer-corpus
    deck: Path | None = None  # the deck JSON, when it is not in the repository


@dataclass(frozen=True)
class IntakeResult:
    code: str
    bundle: Path
    deck_where: str
    speaker: Speaker
    lect: str
    corpus_id: str
    corpus: Path
    created: bool
    source: str
    manifest: Path
    pack: Path
    per_set: dict[str, int]  # clips kept per set, in deck order
    skipped: list[str]
    kept_out: dict[str, str]


def _read(path: Path) -> Bundle:
    try:
        return read_bundle(path)
    except BundleError as e:
        raise IntakeError(str(e)) from e


def _refuse_if_present(root: Path, code: str) -> None:
    trace = find_session(root, code)
    if trace.corpora:
        where = "; ".join(f"corpus {t.corpus_id} ({t.summary()})" for t in trace.corpora)
        raise IntakeError(f"session {code} is already in {where}; to take it in again, purge it first: "
                          f"tkh purge --session {code}")  # fmt: skip


def _refuse_unusable_dir(corpus: Path, created: bool) -> None:
    if created and corpus.exists() and any(corpus.iterdir()):
        raise IntakeError(f"{corpus} exists but has no corpus.toml; move it away or pass another --corpus")


def _discard_staging(root: Path, code: str) -> None:
    """Best effort: a staging area that cannot be removed now is removed by the next intake or
    purge of the session, and must not hide the outcome."""
    try:
        clear_leftovers(root, code)
    except OSError:
        pass


def _commit(staged: Staged, corpus: Path, created: bool, code: str) -> None:
    if created:
        move_dir_into_place(staged.dir, corpus)
        return
    apply_all([
        MoveNew(staged.audio, layout.audio_dir(corpus, code)),
        MoveNew(staged.session_copy, layout.session_copy(corpus, code)),
        Replace(staged.manifest, corpus / staged.manifest.relative_to(staged.dir)),
        Replace(staged.corpus_toml, corpus / "corpus.toml"),
    ])  # fmt: skip


def intake_bundle(path: Path, opts: IntakeOptions) -> IntakeResult:
    """Take one bundle (zip or unzipped folder) into a corpus. Raises `IntakeError` (or `OSError`)
    with nothing written."""
    bundle = _read(path)
    session = bundle.session
    code = session.session
    _refuse_if_present(opts.root, code)
    found = find_deck(session.deck, repo=opts.repo, explicit=opts.deck)
    deck = found.deck
    pack = pack_path(opts.repo, deck.deck.lect)
    corpus_id = opts.corpus_id or layout.default_corpus_id(deck.deck.id)
    base, created = existing_or_new(
        opts.root, corpus_id, lect=deck.deck.lect, pack=pack, source=opts.source, register=opts.register
    )
    speaker = session_speaker(session)
    updated = with_speaker(base, speaker, pack)
    corpus = corpus_dir(opts.root, corpus_id)
    _refuse_unusable_dir(corpus, created)
    manifest = corpus / updated.corpus.manifest
    joined = join_session(
        session,
        deck,
        source=updated.corpus.source,
        path_of=lambda card: layout.manifest_relpath(corpus, manifest, code, card),
    )
    if not joined.rows:
        raise IntakeError(f"session {code} has no clip to keep (every card skipped or kept out); nothing written")
    manifest_ids(manifest, opts.register)  # refuse a corpus manifest that is already broken
    old = manifest.read_text(encoding="utf-8") if manifest.exists() else ""
    clear_leftovers(opts.root, code)
    try:
        staged = stage(
            opts.root,
            bundle,
            [r.card for r in joined.rows if r.card is not None],
            manifest_name=updated.corpus.manifest,
            manifest_text=appended(old, [r.model_dump_json() for r in joined.rows]),
            corpus_text=corpus_toml_text(updated),
        )
        check_staged(staged, register=opts.register, pack=pack)
        _commit(staged, corpus, created, code)
    except BaseException:
        _discard_staging(opts.root, code)
        raise
    _discard_staging(opts.root, code)
    per_set = Counter(r.set for r in joined.rows)
    return IntakeResult(
        code=code,
        bundle=path,
        deck_where=found.where,
        speaker=speaker,
        lect=deck.deck.lect,
        corpus_id=corpus_id,
        corpus=corpus,
        created=created,
        source=updated.corpus.source,
        manifest=manifest,
        pack=pack,
        per_set=dict(per_set),
        skipped=list(session.skipped),
        kept_out=joined.kept_out,
    )
