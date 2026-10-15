"""Intake's staging area: everything a session adds to a corpus, written first under
`corpora/.intake-<CODE>-<pid>/` in the corpus's own layout. Only when all of it is written and
checked does `commit` move it into the corpus."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..contracts.bundle import Bundle
from . import layout
from .commit import remove_tree


@dataclass(frozen=True)
class Staged:
    dir: Path
    audio: Path
    session_copy: Path
    manifest: Path
    corpus_toml: Path


def clear_leftovers(root: Path, code: str) -> None:
    """Remove staging areas of `code` that a killed intake left behind."""
    for d in layout.staging_dirs(root, code):
        remove_tree(d)


def stage(
    root: Path,
    bundle: Bundle,
    cards: list[str],
    *,
    manifest_name: str,
    manifest_text: str,
    corpus_text: str,
) -> Staged:
    """Write the session's clips (byte for byte), its session.json, the corpus's new manifest
    and corpus.toml into a fresh staging area."""
    code = bundle.session.session
    d = layout.staging_dir(root, code)
    d.mkdir(parents=True)
    staged = Staged(
        dir=d,
        audio=layout.audio_dir(d, code),
        session_copy=layout.session_copy(d, code),
        manifest=d / manifest_name,
        corpus_toml=d / "corpus.toml",
    )
    staged.audio.mkdir(parents=True)
    for card in cards:
        layout.clip_file(d, code, card).write_bytes(bundle.clip_bytes(card))
    staged.session_copy.parent.mkdir(parents=True)
    staged.session_copy.write_bytes(bundle.session_bytes())
    staged.manifest.parent.mkdir(parents=True, exist_ok=True)
    staged.manifest.write_text(manifest_text, encoding="utf-8")
    staged.corpus_toml.write_text(corpus_text, encoding="utf-8")
    return staged
