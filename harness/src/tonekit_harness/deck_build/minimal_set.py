"""`diag_minimal`: sets of real words that differ only in tone (买/卖). Every card is a correct
reading of its own word; the other words of its set are its distractors, and `pair` only groups
the set (R76).

Columns: group (m01, ...), text, pinyin; optional text_traditional, context (isolated by default,
the words are read on their own), flag. The words of a set share their toneless syllables (买 and
卖 are both mai) and differ in tone. A word's candidate id is its numbered pinyin (`mai3`), which
also names it as a distractor."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .cards import candidate, make_card
from .errors import BuildError
from .reading import RULES, Reading
from .rows import Row, read_rows

COLUMNS = ["group", "text", "pinyin"]
OPTIONAL = ["text_traditional", "context", "flag"]


def numbered(pinyin: str) -> str:
    """`mǎi` -> `mai3`; a word of several syllables joins them (`yi4bei1`)."""
    return "".join(f"{s.base}{s.tone}" for s in RULES.parse_pinyin(pinyin))


def toneless(pinyin: str) -> str:
    """`mǎi` -> `mai`; the toneless syllables of a word, which the words of a minimal set share."""
    return " ".join(s.base for s in RULES.parse_pinyin(pinyin))


def _check_syllables(group: str, members: list[Row]) -> None:
    sounds = []
    for row in members:
        try:
            sounds.append(toneless(row.need("pinyin")))
        except ValueError as e:
            raise BuildError(f"{row.where}: pinyin: {e}") from e
    if len(set(sounds)) > 1:
        shown = ", ".join(f"{r.need('text')} ({s})" for r, s in zip(members, sounds, strict=True))
        raise BuildError(
            f"{members[0].where}: set {group} mixes syllables: {shown}; "
            "the words of a minimal set share their toneless syllables and differ in tone"
        )


def _reading(row: Row) -> Reading:
    pinyin = row.need("pinyin")
    return Reading(
        row.need("text"), pinyin, pinyin, row.get("context", "isolated"), row.get("text_traditional") or None
    )  # fmt: skip


def minimal_cards(path: str | Path) -> tuple[list[dict], dict[str, str]]:
    groups: dict[str, list[Row]] = defaultdict(list)
    for row in read_rows(path, required=COLUMNS, optional=OPTIONAL):
        groups[row.need("group")].append(row)
    cards: list[dict] = []
    flags: dict[str, str] = {}
    for group, members in groups.items():
        if len(members) < 2:
            raise BuildError(f"{members[0].where}: set {group} has one word; a minimal set needs two or more")
        _check_syllables(group, members)
        ids = [numbered(r.need("pinyin")) for r in members]
        if len(set(ids)) != len(ids):
            raise BuildError(f"{members[0].where}: set {group} lists the same word twice")
        for i, row in enumerate(members):
            others = [candidate(ids[j], members[j].need("pinyin")) for j in range(len(members)) if j != i]
            card_id = f"{group}-{'abcdefgh'[i]}"
            cards.append(
                make_card(
                    id=card_id,
                    set="diag_minimal",
                    pair=group,
                    label="correct",
                    reading=_reading(row),
                    intended=candidate(ids[i], row.need("pinyin")),
                    distractors=others,
                )  # fmt: skip
            )
            if row.get("flag"):
                flags[card_id] = row.get("flag")
    return cards, flags
