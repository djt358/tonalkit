"""`tkh intake` for one bundle: read and check it, find its deck, build the rows and the speaker
entry, stage everything, check it, then move it into the corpus in one change. A refusal or a
failure leaves the data root as it was."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..contracts.bundle import Bundle, BundleError, read_bundle
from ..contracts.registry import CorpusFile, Speaker, corpus_dir
from . import layout
from .checks import check_staged, manifest_ids
from .commit import MoveNew, Replace, apply_all, move_dir_into_place
from .corpus_toml import corpus_toml_text
from .corpus_update import existing_or_new, session_speaker, with_speaker
from .deck_lookup import find_deck
from .errors import IntakeError
from .manifest_lines import appended
from .packs import pack_path
from .rows import Joined, join_session
from .silence import silent_cards
from .stage import Staged, clear_leftovers, stage
from .trace import find_session, manifest_text


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
    silent: list[str]  # recorded cards with no sound: no row, no audio
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


@dataclass(frozen=True)
class _Plan:
    """Everything a session adds, worked out and checked before anything is written."""

    bundle: Bundle
    deck_where: str
    lect: str
    pack: Path
    corpus_id: str
    corpus: Path
    created: bool
    updated: CorpusFile  # the corpus file with the session's speaker
    speaker: Speaker
    manifest: Path
    manifest_text: str  # the corpus's manifest with the session's rows appended
    joined: Joined


def _plan(path: Path, opts: IntakeOptions) -> _Plan:
    bundle = _read(path)
    session = bundle.session
    code = session.session
    _refuse_if_present(opts.root, code)
    found = find_deck(session.deck, repo=opts.repo, explicit=opts.deck)
    lect = found.deck.deck.lect
    pack = pack_path(opts.repo, lect)
    corpus_id = opts.corpus_id or layout.default_corpus_id(found.deck.deck.id)
    base, created = existing_or_new(
        opts.root, corpus_id, lect=lect, pack=pack, source=opts.source, register=opts.register
    )
    speaker = session_speaker(session)
    updated = with_speaker(base, speaker, pack)
    corpus = corpus_dir(opts.root, corpus_id)
    _refuse_unusable_dir(corpus, created)
    manifest = corpus / updated.corpus.manifest
    joined = join_session(
        session,
        found.deck,
        source=updated.corpus.source,
        path_of=lambda card: layout.manifest_relpath(corpus, manifest, code, card),
        silent=silent_cards(bundle),
    )
    if not joined.rows:
        raise IntakeError(
            f"session {code} has no clip to keep (every card skipped, silent or kept out); nothing written"
        )
    old = manifest_text(manifest)
    manifest_ids(manifest, opts.register)  # refuse a corpus manifest that is already broken
    return _Plan(
        bundle=bundle, deck_where=found.where, lect=lect, pack=pack, corpus_id=corpus_id, corpus=corpus,
        created=created, updated=updated, speaker=speaker, manifest=manifest,
        manifest_text=appended(old, [r.model_dump_json() for r in joined.rows]), joined=joined,
    )  # fmt: skip


def _write(plan: _Plan, opts: IntakeOptions) -> None:
    """Stage, check, move in; on any failure, discard the staging area and re-raise."""
    code = plan.bundle.session.session
    clear_leftovers(opts.root, code)
    try:
        staged = stage(
            opts.root,
            plan.bundle,
            [r.card for r in plan.joined.rows if r.card is not None],
            manifest_name=plan.updated.corpus.manifest,
            manifest_text=plan.manifest_text,
            corpus_text=corpus_toml_text(plan.updated),
        )
        check_staged(staged, register=opts.register, pack=plan.pack)
        _commit(staged, plan.corpus, plan.created, code)
    except BaseException:
        _discard_staging(opts.root, code)
        raise
    _discard_staging(opts.root, code)


def _result(path: Path, plan: _Plan) -> IntakeResult:
    session = plan.bundle.session
    return IntakeResult(
        code=session.session,
        bundle=path,
        deck_where=plan.deck_where,
        speaker=plan.speaker,
        lect=plan.lect,
        corpus_id=plan.corpus_id,
        corpus=plan.corpus,
        created=plan.created,
        source=plan.updated.corpus.source,
        manifest=plan.manifest,
        pack=plan.pack,
        per_set=dict(Counter(r.set for r in plan.joined.rows)),
        skipped=list(session.skipped),
        silent=plan.joined.silent,
        kept_out=plan.joined.kept_out,
    )


def intake_bundle(path: Path, opts: IntakeOptions) -> IntakeResult:
    """Take one bundle (zip or unzipped folder) into a corpus. Raises `IntakeError` (or `OSError`)
    with nothing written."""
    plan = _plan(path, opts)
    _write(plan, opts)
    return _result(path, plan)
