"""`diag_t23`: pairs on the second/third tone confusion and the half-third tone, each a correct
reading and a deliberate error that differs in one surface tone. Unlike the gate, both phrases are
written out in the source, so the changed syllable can be anywhere.

Columns: text, citation_pinyin, spoken_pinyin, error_text, error_citation_pinyin,
error_spoken_pinyin, as_in (a common word with the changed character), gloss; optional
text_traditional, error_text_traditional, as_in_traditional (for the note in traditional
characters, R88), flag. The prompt note names the one character that differs."""

from __future__ import annotations

from pathlib import Path

from .errors import BuildError
from .notes import error_note
from .pairs import pair_cards
from .reading import Reading
from .rows import Row, read_rows

COLUMNS = [
    "text", "citation_pinyin", "spoken_pinyin", "error_text", "error_citation_pinyin",
    "error_spoken_pinyin", "as_in", "gloss",
]  # fmt: skip
OPTIONAL = ["text_traditional", "error_text_traditional", "as_in_traditional", "flag"]


def changed_character(text: str, error_text: str, where: str) -> str:
    """The one character of `error_text` that is not the same as `text` at its place."""
    if len(text) != len(error_text):
        raise BuildError(f"{where}: {text} and {error_text} differ in length")
    differing = [e for t, e in zip(text, error_text, strict=True) if t != e]
    if len(differing) != 1:
        raise BuildError(f"{where}: {text} and {error_text} differ in {len(differing)} characters; it must be one")
    return differing[0]


def _pair(row: Row, pair: str) -> tuple[dict, dict]:
    correct = Reading(
        row.need("text"), row.need("citation_pinyin"), row.need("spoken_pinyin"),
        "phrase", row.get("text_traditional") or None,
    )  # fmt: skip
    error = Reading(
        row.need("error_text"), row.need("error_citation_pinyin"), row.need("error_spoken_pinyin"),
        "phrase", row.get("error_text_traditional") or None,
    )  # fmt: skip
    char = changed_character(correct.text, error.text, row.where)
    note = error_note(char, row.need("as_in"), row.need("gloss"))
    traditional = _traditional_note(row, correct, error, char)
    return pair_cards("diag_t23", pair, correct, error, note=note, note_traditional=traditional)


def _traditional_note(row: Row, correct: Reading, error: Reading, char: str) -> str:
    """The note with the changed character and the example word in traditional forms (the simplified
    ones where the row gives none)."""
    if correct.text_traditional and error.text_traditional:
        char = changed_character(correct.text_traditional, error.text_traditional, row.where)
    return error_note(char, row.get("as_in_traditional", row.need("as_in")), row.need("gloss"))


def t23_cards(path: str | Path) -> tuple[list[dict], dict[str, str]]:
    cards: list[dict] = []
    flags: dict[str, str] = {}
    for i, row in enumerate(read_rows(path, required=COLUMNS, optional=OPTIONAL), start=1):
        c, e = _pair(row, f"t{i:02d}")
        cards += [c, e]
        if row.get("flag"):
            flags[c["id"]] = row.get("flag")
    return cards, flags
