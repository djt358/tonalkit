"""Sets of single cards (no pairs): `register`, `diag_context` and `diag_count`.

Columns: text, citation_pinyin, spoken_pinyin; optional text_traditional, context (isolated or
phrase), repeat (the row becomes that many cards), note (shown under the card), flag (what DJ
should look at), status. For a hesitation card the pinyin columns cover only the spell, and the
text also shows the hesitation, so the produced tones are the spell's alone."""

from __future__ import annotations

from pathlib import Path

from .cards import candidate, make_card
from .errors import BuildError
from .reading import Reading
from .rows import Row, read_rows

COLUMNS = ["text", "citation_pinyin", "spoken_pinyin"]
OPTIONAL = ["text_traditional", "context", "repeat", "note", "flag", "status"]


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


def single_cards(path: str | Path, *, set_: str, prefix: str, context: str | None) -> tuple[list[dict], dict[str, str]]:
    """The cards of the CSV at `path`, ids `<prefix>01`, `<prefix>02`, ... in order, and the flags.
    `context` is the default for rows without a context column; None makes the column required."""
    cards: list[dict] = []
    flags: dict[str, str] = {}
    for row in read_rows(path, required=COLUMNS, optional=OPTIONAL):
        reading = Reading(
            row.need("text"), row.need("citation_pinyin"), row.need("spoken_pinyin"),
            _context(row, context), row.get("text_traditional") or None,
        )  # fmt: skip
        for _ in range(_repeat(row)):
            card_id = f"{prefix}{len(cards) + 1:02d}"
            cards.append(
                make_card(
                    id=card_id,
                    set=set_,
                    label="correct",
                    reading=reading,
                    intended=candidate(card_id, reading.spoken_pinyin),
                    note=row.get("note"),
                    status=row.get("status", "unverified"),
                )  # fmt: skip
            )
            if row.get("flag"):
                flags[card_id] = row.get("flag")
    return cards, flags
