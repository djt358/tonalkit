"""`diag_minimal`: sets of real words that differ only in tone (买/卖). Every card is a correct
reading of its own word; the other words of its set are its distractors, and `pair` only groups
the set (R76).

Columns: group (m01, ...), text, pinyin; optional text_traditional, context (isolated by default,
the words are read on their own), flag, status. A word's candidate id is its numbered pinyin
(`mai3`), which also names it as a distractor."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .cards import candidate, make_card
from .errors import BuildError
from .reading import RULES, Reading
from .rows import Row, read_rows

COLUMNS = ["group", "text", "pinyin"]
OPTIONAL = ["text_traditional", "context", "flag", "status"]


def numbered(pinyin: str) -> str:
    """`mǎi` -> `mai3`; a word of several syllables joins them (`yi4bei1`)."""
    return "".join(f"{s.base}{s.tone}" for s in RULES.parse_pinyin(pinyin))


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
                    status=row.get("status", "unverified"),
                )  # fmt: skip
            )
            if row.get("flag"):
                flags[card_id] = row.get("flag")
    return cards, flags
