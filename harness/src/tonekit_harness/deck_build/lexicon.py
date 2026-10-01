"""The tone-variant lexicon (`tone_variants.csv`): for a character, real characters with the same
syllable and a different tone, each with a word that shows how it is normally used. The builder
draws deliberate-error substitutions from it, so every error card is made of a character somebody
vetted, never a guess.

Columns: char, pinyin (its tone-marked syllable), variant, variant_pinyin (same syllable, other
tone), variant_traditional (blank when the same), as_in (a common word with the variant),
as_in_traditional (blank when the same), gloss (English), flag (what DJ should look at; may be
empty)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .errors import BuildError
from .reading import RULES
from .rows import Row, read_rows

COLUMNS = ["char", "pinyin", "variant", "variant_pinyin", "as_in", "gloss"]
OPTIONAL = ["variant_traditional", "as_in_traditional", "flag"]


@dataclass(frozen=True)
class Variant:
    char: str
    pinyin: str
    variant: str
    variant_pinyin: str
    variant_traditional: str
    as_in: str
    as_in_traditional: str
    gloss: str
    flag: str

    def note(self) -> str:
        """The prompt note of an error card made with this variant."""
        return f"Read it as written: {self.variant} as in {self.as_in} ({self.gloss})."


class Lexicon:
    def __init__(self, variants: list[Variant]):
        self._by_char: dict[str, list[Variant]] = defaultdict(list)
        for v in variants:
            self._by_char[v.char].append(v)

    def variants(self, char: str) -> list[Variant]:
        """The variants of `char`, in file order."""
        return list(self._by_char.get(char, ()))

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_char.values())


def _variant(row: Row) -> Variant:
    char, variant = row.need("char"), row.need("variant")
    if len(char) != 1 or len(variant) != 1:
        raise BuildError(f"{row.where}: char and variant must each be one character")
    trad = row.get("variant_traditional", variant)
    if len(trad) != 1:
        raise BuildError(f"{row.where}: variant_traditional must be one character")
    a, b = _one_syllable(row, "pinyin"), _one_syllable(row, "variant_pinyin")
    if a.base != b.base or a.tone == b.tone:
        raise BuildError(
            f"{row.where}: {row.get('pinyin')} and {row.get('variant_pinyin')} must be the same "
            "syllable in different tones"
        )
    return Variant(
        char, row.need("pinyin"), variant, row.need("variant_pinyin"), trad,
        row.need("as_in"), row.get("as_in_traditional", row.need("as_in")), row.need("gloss"), row.get("flag"),
    )  # fmt: skip


def _one_syllable(row: Row, column: str):
    try:
        syllables = RULES.parse_pinyin(row.need(column))
    except ValueError as e:
        raise BuildError(f"{row.where}: {column}: {e}") from e
    if len(syllables) != 1:
        raise BuildError(f"{row.where}: {column} must be one syllable")
    return syllables[0]


def load_lexicon(path: str | Path) -> Lexicon:
    return Lexicon([_variant(r) for r in read_rows(path, required=COLUMNS, optional=OPTIONAL)])
