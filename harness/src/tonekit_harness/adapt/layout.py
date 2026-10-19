"""Where `tkh adapt` puts a public corpus's files under the data root (docs/s05/contracts.md
section 3). Nothing else names these paths:

    corpora/<corpus>/corpus.toml, manifest.jsonl
    corpora/<corpus>/audio/<speaker>/<utterance>.wav   16 kHz mono PCM16
    corpora/.adapt-<corpus>-<pid>/                     the new corpus, staged while adapt runs
    corpora/.adapt-<corpus>-<pid>.old/                 the corpus it replaces, until the new one is in
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..contracts.registry import SPEAKER_ID_PATTERN

AUDIO_DIR = "audio"
MANIFEST = "manifest.jsonl"
STAGING_PREFIX = ".adapt-"
SAFE_ID = re.compile(SPEAKER_ID_PATTERN)  # utterance and speaker ids name files: no `/`, no `..`


def staging_dir(root: Path, corpus_id: str) -> Path:
    return root / "corpora" / f"{STAGING_PREFIX}{corpus_id}-{os.getpid()}"


def aside_dir(root: Path, corpus_id: str) -> Path:
    return root / "corpora" / f"{STAGING_PREFIX}{corpus_id}-{os.getpid()}.old"


def leftovers(root: Path, corpus_id: str) -> list[Path]:
    """Staging and set-aside directories of `corpus_id` that a killed `tkh adapt` left behind
    (not those of a corpus whose id merely starts the same)."""
    base = root / "corpora"
    if not base.is_dir():
        return []
    mine = re.compile(rf"{re.escape(STAGING_PREFIX + corpus_id)}-\d+(\.old)?")
    return sorted(p for p in base.iterdir() if p.is_dir() and mine.fullmatch(p.name))


def audio_relpath(speaker: str, utterance: str) -> str:
    """The clip's path as its manifest row names it, relative to the corpus directory."""
    return f"{AUDIO_DIR}/{speaker}/{utterance}.wav"


def safe_id(name: str) -> bool:
    """Whether a corpus's id can name a file or folder here (letters, digits, `._-`, no `/`)."""
    return bool(SAFE_ID.fullmatch(name))
