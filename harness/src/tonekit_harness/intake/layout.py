"""Where intake puts a session's files in a corpus, and so where purge looks for them
(docs/s05/contracts.md sections 3 and 6). Nothing else names these paths:

    corpora/<corpus>/audio/<CODE>/<card>.wav     the bundle's clips, byte for byte
    corpora/<corpus>/sessions/<CODE>.json        the bundle's session.json, byte for byte
    corpora/.intake-<CODE>-<pid>/                intake's staging area while it runs
    corpora/<corpus>/relabels.jsonl              `tkh relabel`'s log: what a listener decided per clip
    corpora/<corpus>/.<manifest>.relabel-<pid>   relabel's new manifest while it is checked
    reports/<corpus>.md                          where `tkh eval` is told to write its report
    reports/<corpus>.results.json                ... and its per-clip results, which `tkh review` reads
    review/<corpus>/                             `tkh review`'s page, which links the corpus's audio
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

AUDIO_DIR = "audio"
SESSIONS_DIR = "sessions"
STAGING_PREFIX = ".intake-"
RELABEL_LOG = "relabels.jsonl"
REVIEW_DIR = "review"
DEFAULT_CORPUS_PREFIX = "volunteers-"


def corpora_dir(root: Path) -> Path:
    return root / "corpora"


def corpus_ids(root: Path) -> list[str]:
    """Every corpus directory under the data root (with or without a corpus.toml), sorted; intake's
    staging areas and other dot-directories are not corpora."""
    base = corpora_dir(root)
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))


def default_corpus_id(deck_id: str) -> str:
    """The corpus a bundle goes to without `--corpus`: one per deck, so every volunteer who read
    the same cards is graded together."""
    return f"{DEFAULT_CORPUS_PREFIX}{deck_id}"


def audio_dir(corpus: Path, code: str) -> Path:
    return corpus / AUDIO_DIR / code


def clip_file(corpus: Path, code: str, card: str) -> Path:
    return audio_dir(corpus, code) / f"{card}.wav"


def session_copy(corpus: Path, code: str) -> Path:
    return corpus / SESSIONS_DIR / f"{code}.json"


def staging_dir(root: Path, code: str) -> Path:
    return corpora_dir(root) / f"{STAGING_PREFIX}{code}-{os.getpid()}"


def staging_dirs(root: Path, code: str) -> list[Path]:
    """Staging areas of `code` left by an intake that was killed before it finished."""
    base = corpora_dir(root)
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob(f"{STAGING_PREFIX}{code}-*") if p.is_dir())


def clip_id(code: str, card: str) -> str:
    return f"{code}-{card}"


def pair_id(code: str, pair: str | None) -> str | None:
    """A deck pair within one session: `<CODE>-<pair>`. The manifest holds many speakers, and a
    gate pair is one speaker's correct and error reading."""
    return None if pair is None else f"{code}-{pair}"


def manifest_relpath(corpus: Path, manifest: Path, code: str, card: str) -> str:
    """The clip's path as a manifest row names it: relative to the manifest's directory, POSIX."""
    return PurePosixPath(Path(os.path.relpath(clip_file(corpus, code, card), manifest.parent))).as_posix()


def is_session_row(row: dict, corpus: Path, manifest: Path, code: str) -> bool:
    """Whether a manifest row (its JSON object) is one intake wrote for `code`: its id is
    `<CODE>-...` or its audio is in the session's audio directory."""
    if str(row.get("id", "")).startswith(f"{code}-"):
        return True
    path = row.get("path")
    if not isinstance(path, str):
        return False
    target = Path(os.path.normpath(manifest.parent / path))
    return target.parent == Path(os.path.normpath(audio_dir(corpus, code)))


def report_path(root: Path, corpus_id: str) -> Path:
    """Under the data root: a report names clips by session code and lists per-clip scores."""
    return root / "reports" / f"{corpus_id}.md"


def results_path(root: Path, corpus_id: str) -> Path:
    """Where `tkh eval` is told to write its per-clip results (`eval_results`), beside the report;
    `tkh review` reads them from here by default."""
    return root / "reports" / f"{corpus_id}.results.json"


def relabel_temp(manifest: Path) -> Path:
    """Where `tkh relabel` writes the new manifest to check it before it replaces the old one."""
    return manifest.with_name(f".{manifest.name}.relabel-{os.getpid()}")


def relabel_temps(corpus: Path) -> list[Path]:
    """New manifests a killed `tkh relabel` left in the corpus directory: they hold every
    session's rows, so relabel and purge remove them."""
    return sorted(p for p in corpus.glob(".*.relabel-*") if p.is_file()) if corpus.is_dir() else []


def relabel_log(corpus: Path) -> Path:
    """`tkh relabel`'s append-only log in the corpus directory (`contracts.relabel`)."""
    return corpus / RELABEL_LOG


def review_root(root: Path) -> Path:
    return root / REVIEW_DIR


def review_dir(root: Path, corpus_id: str) -> Path:
    """`tkh review`'s page for a corpus: under the data root, since it links the volunteers' audio
    and names their clips; purge removes a page that mentions the session."""
    return review_root(root) / corpus_id
