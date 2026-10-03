"""DJ's g_measure table as the source of gate phrases: `tkh deck build --gmeasure PATH`.

The table's own columns are not fixed here. Each field the builder needs is looked up under the
names in ALIASES (first one present in the header wins), or under the column named with
`--gmeasure-map FIELD=COLUMN`. The phrase may also be put together from a measure word column and a
noun column (the numeral column if there is one, otherwise "一", + measure + word). Pinyin written
in words ("kāfēi") is spaced into syllables. Columns that are not listed (weight, referent, register, tile
ids, DJ's status) are ignored. The pinyin columns are DJ's own and are checked against the sandhi
rules like everything else: a row whose spoken pinyin disagrees is reported, not used."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .errors import BuildError
from .gate import GateRow
from .gate_select import Left
from .pinyin_spacing import space_pinyin
from .reading import Reading
from .rows import read_rows

ALIASES = {
    "text": ("phrase", "text", "tier2", "tier2_phrase", "phrase_zh", "zh", "hanzi", "example"),
    "citation_pinyin": ("citation_pinyin",),
    "spoken_pinyin": ("spoken_pinyin",),
    "text_traditional": ("text_traditional", "traditional", "phrase_traditional"),
    "numeral": ("numeral", "num"),
    "measure": ("measure", "measure_word", "classifier", "mw"),
    "word": ("word", "noun"),
}


def resolve_columns(header: list[str], overrides: Mapping[str, str]) -> dict[str, str | None]:
    """Field -> the column of `header` that holds it (None when the table has none)."""
    for field in overrides:
        if field not in ALIASES:
            raise BuildError(f"--gmeasure-map: unknown field {field!r} (fields: {', '.join(ALIASES)})")
    found: dict[str, str | None] = {}
    for field, names in ALIASES.items():
        wanted = [overrides[field]] if field in overrides else list(names)
        found[field] = next((n for n in wanted if n in header), None)
        if field in overrides and found[field] is None:
            raise BuildError(
                f"--gmeasure-map: no column {overrides[field]!r} for {field} (header: {', '.join(header)})"
            )
    return found


def _need_columns(found: Mapping[str, str | None], path: Path, header: list[str]) -> None:
    missing = [f for f in ("citation_pinyin", "spoken_pinyin") if found[f] is None]
    if found["text"] is None and not (found["measure"] and found["word"]):
        missing.append("text (or measure and word)")
    if missing:
        raise BuildError(
            f"{path}: no column for {', '.join(missing)} (header: {', '.join(header)}); "
            "name one with --gmeasure-map FIELD=COLUMN"
        )


def read_gmeasure(path: str | Path, overrides: Mapping[str, str] | None = None) -> tuple[list[GateRow], list[Left]]:
    """The table's rows as gate rows, and the rows that have no phrase or no pinyin."""
    path = Path(path)
    rows = read_rows(path, required=[], strict=False)
    if not rows:
        raise BuildError(f"{path}: no rows")
    header = list(rows[0].values)
    cols = resolve_columns(header, overrides or {})
    _need_columns(cols, path, header)

    def value(row, field: str) -> str:
        return row.get(cols[field]) if cols[field] else ""

    def phrase(row) -> str:
        if text := value(row, "text"):
            return text
        measure, word = value(row, "measure"), value(row, "word")
        return (value(row, "numeral") or "一") + measure + word if measure and word else ""

    gate_rows: list[GateRow] = []
    left: list[Left] = []
    for row in rows:
        text = phrase(row)
        citation, spoken = value(row, "citation_pinyin"), value(row, "spoken_pinyin")
        if not text:
            left.append(Left(row.where, "", "no phrase (no text, or no measure word or noun to make one)"))
        elif not citation or not spoken:
            left.append(Left(row.where, text, "citation_pinyin or spoken_pinyin is empty"))
        else:
            reading = Reading(
                text, space_pinyin(citation), space_pinyin(spoken), "phrase", value(row, "text_traditional") or None
            )
            gate_rows.append(GateRow(row.where, reading))
    return gate_rows, left
