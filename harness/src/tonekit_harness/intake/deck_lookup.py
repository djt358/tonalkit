"""The deck a bundle was recorded with. A bundle names the deck's id and the sha256 of the exact
JSON the phone fetched; the deck is that file: `--deck PATH`, else `kit/deck/<id>.json` in the
repository, else the version in its git history with that hash. A file with another hash is never
used: its cards might say something else than what the speaker read."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..contracts.bundle import DeckRef
from ..contracts.deck import Deck, DeckError, parse_deck
from .deck_history import file_versions
from .errors import IntakeError


@dataclass(frozen=True)
class FoundDeck:
    deck: Deck
    where: str  # where it came from, for the summary


def deck_relpath(deck_id: str) -> str:
    return f"kit/deck/{deck_id}.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _parse(data: bytes, where: str) -> FoundDeck:
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise IntakeError(f"{where}: not a deck JSON file: {e}") from e
    if not isinstance(doc, dict):
        raise IntakeError(f"{where}: not a deck JSON file (expected an object)")
    try:
        return FoundDeck(deck=parse_deck(doc, source=where), where=where)
    except DeckError as e:
        raise IntakeError(str(e)) from e


def _how_to_pass(ref: DeckRef) -> str:
    return (
        f"pass the exact file the kit served with --deck PATH (the site's deck/{ref.id}.json "
        "from when the speaker recorded)"
    )


def _explicit(ref: DeckRef, path: Path) -> FoundDeck:
    try:
        data = path.read_bytes()
    except OSError as e:
        raise IntakeError(f"--deck {path}: cannot read it: {e.strerror or e}") from e
    if _sha(data) != ref.sha256:
        raise IntakeError(
            f"--deck {path} has sha256 {_sha(data)}, but the bundle was recorded with deck "
            f"{ref.id!r} sha256 {ref.sha256}; {_how_to_pass(ref)}"
        )
    return _parse(data, str(path))


def find_deck(ref: DeckRef, *, repo: Path, explicit: Path | None = None) -> FoundDeck:
    """The deck whose JSON has the bundle's hash. Raises `IntakeError` naming the bundle's hash,
    the hash of the deck file in the repository and how to pass the right file."""
    if explicit is not None:
        return _explicit(ref, explicit)
    rel = deck_relpath(ref.id)
    current = repo / rel
    current_sha = None
    if current.is_file():
        data = current.read_bytes()
        current_sha = _sha(data)
        if current_sha == ref.sha256:
            return _parse(data, rel)
    earlier = 0
    for commit, data in file_versions(repo, rel):
        earlier += 1
        if _sha(data) == ref.sha256:
            return _parse(data, f"{rel} at commit {commit[:12]}")
    has = f"has sha256 {current_sha}" if current_sha else "does not exist"
    raise IntakeError(
        f"deck {ref.id!r}: no version matches the bundle. The bundle was recorded with deck sha256 "
        f"{ref.sha256}; {rel} in the repository {has}, and none of its {earlier} committed "
        f"version(s) match; {_how_to_pass(ref)}"
    )
