"""`tkh adapt` for one downloaded corpus: refuse a source the data register does not allow, read the
corpus's files, plan the rows, then stage the audio, manifest and corpus.toml, check them as
`tkh eval` and the registry will read them, and put the corpus in place in one step. A refusal
or a failure leaves the data root as it was; running it again on the same download changes
nothing."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from ..contracts.registry import CORPUS_ID_PATTERN, RegistryError, corpus_dir, load_corpus_file
from ..intake.checks import check_new_files
from ..intake.commit import remove_tree
from ..intake.corpus_toml import corpus_toml_text
from ..intake.layout import RELABEL_LOG
from ..intake.packs import pack_path
from ..intake.stale import mark_stale
from ..manifest import Clip
from . import drops, layout
from .audio import converted
from .corpus_files import AdaptError
from .plan import Plan, plan
from .replace import put_in_place
from .speakers import LECT, corpus_file

# R123: the length probe (harness/scripts/length_probe.py) found no length at which the forced
# decode or `tkh eval` breaks down on synthetic phrases up to 48 syllables; see decisions.md.
DEFAULT_MAX_SYLLABLES = 32


@dataclass(frozen=True)
class AdaptOptions:
    root: Path  # the data root
    repo: Path  # the repository: the pack
    register: Mapping[str, str]  # data-register.csv: id -> shipped_weights_training
    corpus_id: str | None = None  # default: the adapter's name (aishell3, thchs30)
    max_syllables: int = DEFAULT_MAX_SYLLABLES
    limit_speakers: int | None = None


@dataclass(frozen=True)
class AdaptResult:
    adapter: str
    source: str
    src: Path
    corpus_id: str
    corpus: Path
    outcome: str  # created | replaced | unchanged
    manifest: Path
    pack: Path
    plan: Plan
    kept: int  # rows written
    splits: dict[str, list[str]]  # speaker ids per split
    stale: Path | None  # the marker a replaced corpus got


def require_allowed(source: str, register: Mapping[str, str]) -> None:
    """A public corpus is fitting data: its register row must say `allow` (shipped weights and
    training), as for any calibration source."""
    value = register.get(source)
    if value != "allow":
        said = "is not in" if value is None else f"says {value!r} for it in"
        raise AdaptError(
            f"source {source!r}: data-register.csv {said} shipped_weights_training; only 'allow' may be adapted"
        )


def _corpus_id(adapter: ModuleType, wanted: str | None) -> str:
    cid = wanted or adapter.NAME
    if not re.fullmatch(CORPUS_ID_PATTERN, cid):
        raise AdaptError(f"--corpus {cid!r} is not a corpus id (lower-case letters, digits, '.', '_' and '-')")
    return cid


def _refuse_other_corpus(corpus: Path, source: str, pack: Path) -> None:
    """An existing corpus may only be replaced by the same adapter's output: a public corpus of
    the same source, with no listener's relabels to lose."""
    toml = corpus / "corpus.toml"
    if not toml.exists():
        if corpus.exists() and any(corpus.iterdir()):
            raise AdaptError(f"{corpus} exists but has no corpus.toml; move it away or pass another --corpus")
        return
    try:
        meta = load_corpus_file(toml, pack=pack).corpus
    except RegistryError as e:
        raise AdaptError(f"{toml} does not load, so it is not replaced: {e}") from e
    if (meta.kind, meta.source) != ("public", source):
        raise AdaptError(f"{toml}: corpus {meta.id!r} is {meta.kind} from {meta.source!r}, not public from {source!r}")
    if (corpus / RELABEL_LOG).exists():
        raise AdaptError(f"{corpus} has relabels ({RELABEL_LOG}); adapting it again would lose them")


def _stage(staged: Path, p: Plan) -> list[Clip]:
    """Write the kept utterances' audio into `staged`; the rows whose audio converted (the others
    are dropped, and counted)."""
    rows = []
    for planned in p.kept:
        wav = converted(planned.utterance.audio)  # type: ignore[arg-type]
        if wav is None:
            p.dropped.add(drops.BAD_AUDIO, planned.utterance.id)
            continue
        target = staged / planned.row.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(wav)
        rows.append(planned.row)
    return rows


def _by_split(speakers) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in speakers:
        out.setdefault(s.split, []).append(s.id)
    return out


def adapt(adapter: ModuleType, src: Path, opts: AdaptOptions) -> AdaptResult:
    """Adapt the corpus downloaded at `src` with `adapter` (`aishell3`, `thchs30`). Raises
    `AdaptError` (or `IntakeError`, `OSError`) with nothing written."""
    require_allowed(adapter.SOURCE, opts.register)
    if opts.max_syllables < 1:
        raise AdaptError(f"--max-syllables must be at least 1, not {opts.max_syllables}")
    if opts.limit_speakers is not None and opts.limit_speakers < 1:
        raise AdaptError(f"--limit-speakers must be at least 1, not {opts.limit_speakers}")
    cid = _corpus_id(adapter, opts.corpus_id)
    pack = pack_path(opts.repo, LECT)
    corpus = corpus_dir(opts.root, cid)
    _refuse_other_corpus(corpus, adapter.SOURCE, pack)
    found = adapter.read_corpus(src)
    p = plan(
        found, max_syllables=opts.max_syllables, limit_speakers=opts.limit_speakers,
        source=adapter.SOURCE, condition=adapter.CONDITION,
    )  # fmt: skip
    for left in layout.leftovers(opts.root, cid):
        remove_tree(left)
    staged = layout.staging_dir(opts.root, cid)
    staged.mkdir(parents=True)
    try:
        rows = _stage(staged, p)
        if not rows:
            raise AdaptError(f"no utterance of {src} could be kept ({p.dropped.total} dropped); nothing written")
        speakers = sorted({r.speaker for r in rows})
        meta = corpus_file(cid, adapter.SOURCE, speakers, found.speakers, pack)
        (staged / layout.MANIFEST).write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")
        (staged / "corpus.toml").write_text(corpus_toml_text(meta), encoding="utf-8")
        check_new_files(staged / layout.MANIFEST, staged / "corpus.toml", register=opts.register, pack=pack)
        outcome = put_in_place(staged, corpus, layout.aside_dir(opts.root, cid))
    except BaseException:
        if staged.exists():
            remove_tree(staged)
        raise
    stale = None
    if outcome == "replaced":
        reason = f"adapted again from {adapter.NAME} ({len(rows)} clips)"
        stale = mark_stale(opts.root, cid, reason, now=datetime.now(UTC))
    return AdaptResult(
        adapter=adapter.NAME, source=adapter.SOURCE, src=src, corpus_id=cid, corpus=corpus, outcome=outcome,
        manifest=corpus / layout.MANIFEST, pack=pack, plan=p, kept=len(rows),
        splits=_by_split(meta.speaker), stale=stale,
    )  # fmt: skip
