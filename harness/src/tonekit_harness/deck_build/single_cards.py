"""Sets of single cards (no pairs): `register`, `diag_context` and `diag_count`.

Columns: text, citation_pinyin, spoken_pinyin; optional text_traditional, context (isolated or
phrase), repeat (the row becomes that many cards, their notes numbered so identical cards in a row
don't look like the kit is stuck), note (shown under the card), note_traditional
(the note in traditional characters; required when the note names characters, R88), flag (what DJ
should look at). For a hesitation card the pinyin columns cover only the spell, and the
text also shows the hesitation, so the produced tones are the spell's alone."""

from __future__ import annotations

from pathlib import Path

from .cards import candidate, make_card
from .errors import BuildError
from .notes import require_traditional
from .reading import Reading
from .rows import Row, read_rows

COLUMNS = ["text", "citation_pinyin", "spoken_pinyin"]
OPTIONAL = ["text_traditional", "context", "repeat", "note", "note_traditional", "flag"]


def _context(row: Row, default: str | None) -> str:
    context = row.get("context", default or "")
    if context not in ("phrase", "isolated"):
        raise BuildError(f"{row.where}: context must be phrase or isolated, not {context!r}")
    return context


def _repeat(row: Row) -> int:
    text = row.get("repeat", "1")
    if not text.isdigit() or int(text) < 1:
        raise BuildError(f"{row.where}: repeat must be a whole number from 1, not {text!r}")
    return int(text)


def repeat_note(note: str | None, i: int, n: int) -> str | None:
    """The note of repeat `i` of `n`: the first says the card comes up `n` times, the rest count."""
    if n == 1:
        return note
    if i == 1:
        return (
            f"{note} You'll read this card {n} times in a row."
            if note
            else f"You'll read this card {n} times in a row."
        )
    return f"Again, {i} of {n}. {note}" if note else f"Again, {i} of {n}."


def single_cards(path: str | Path, *, set_: str, prefix: str, context: str | None) -> tuple[list[dict], dict[str, str]]:
    """The cards of the CSV at `path`, ids `<prefix>01`, `<prefix>02`, ... in order, and the flags.
    `context` is the default for rows without a context column; None makes the column required."""
    cards: list[dict] = []
    flags: dict[str, str] = {}
    for row in read_rows(path, required=COLUMNS, optional=OPTIONAL):
        require_traditional(row.get("note"), row.get("note_traditional"), row.where)
        reading = Reading(
            row.need("text"), row.need("citation_pinyin"), row.need("spoken_pinyin"),
            _context(row, context), row.get("text_traditional") or None,
        )  # fmt: skip
        n = _repeat(row)
        note, note_traditional = row.get("note"), row.get("note_traditional")
        for i in range(1, n + 1):
            card_id = f"{prefix}{len(cards) + 1:02d}"
            cards.append(
                make_card(
                    id=card_id,
                    set=set_,
                    label="correct",
                    reading=reading,
                    intended=candidate(card_id, reading.spoken_pinyin),
                    note=repeat_note(note, i, n),
                    note_traditional=repeat_note(note_traditional, i, n) if note_traditional else None,
                )  # fmt: skip
            )
            if row.get("flag"):
                flags[card_id] = row.get("flag")
    return cards, flags
