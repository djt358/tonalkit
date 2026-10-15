"""The prompt notes of the deck: the line shown under a card. A note that names characters
("睡 as in 睡觉") is also written with traditional forms, shown instead when the speaker reads
traditional (`prompt_note_traditional`, R88); the builder refuses a note that names characters
and has no traditional version, because a hanzi reader would see simplified forms they may not
know."""

from __future__ import annotations

import re

from .errors import BuildError

_HANZI = re.compile("[㐀-䶿一-鿿豈-﫿]")


def names_characters(note: str) -> bool:
    return _HANZI.search(note) is not None


def error_note(char: str, as_in: str, gloss: str) -> str:
    """The note of a deliberate-error card: what the changed character is and how it is normally
    used, because a reader may not know the character on its own."""
    return f"Read it as written: {char} as in {as_in} ({gloss})."


def require_traditional(note: str, note_traditional: str, where: str) -> None:
    """A note that names characters needs its traditional version (R88)."""
    if names_characters(note) and not note_traditional:
        raise BuildError(f"{where}: the note names characters, so it needs a traditional version (note_traditional)")
