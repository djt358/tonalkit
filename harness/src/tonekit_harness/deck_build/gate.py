"""The gate set: pairs of 一 + measure word + noun phrases, a correct reading (the sandhi form the
speakers produce) and the same phrase with one character swapped for a real tone variant.

The phrases come from rows: DJ's g_measure table when it has arrived (`gmeasure.py`), the stand-in
`gate_standin.csv` until then. A row that cannot make a pair is reported with the reason, and the
pairs are chosen to cover the sandhi cases (`gate_select.py`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import trial
from .errors import BuildError
from .error_word import derive_error
from .gate_select import Left, Usable, select
from .lexicon import Lexicon
from .pairs import pair_cards
from .reading import Reading
from .rows import Row, read_rows

STANDIN_COLUMNS = ["text", "citation_pinyin", "spoken_pinyin"]
STANDIN_OPTIONAL = ["text_traditional", "flag", "status"]


@dataclass(frozen=True)
class GateRow:
    where: str  # file:line, for the report
    reading: Reading
    flag: str = ""
    status: str = "unverified"


@dataclass
class GateBuild:
    cards: list[dict] = field(default_factory=list)
    flags: dict[str, str] = field(default_factory=dict)  # card id -> what DJ should look at
    selected: list[Usable] = field(default_factory=list)
    unusable: list[Left] = field(default_factory=list)  # rows that cannot make a pair
    passed_over: list[Left] = field(default_factory=list)  # usable rows the choice did not need

    def report_lines(self) -> list[str]:
        n = len(self.selected)
        lines = [f"gate: {n} pair{'' if n == 1 else 's'} chosen"]
        lines += [f"  can't use {x.where} {x.text}: {x.reason}" for x in self.unusable]
        lines += [f"  left out  {x.where} {x.text}: {x.reason}" for x in self.passed_over]
        return lines


def standin_rows(path: str | Path) -> list[GateRow]:
    return [_standin_row(r) for r in read_rows(path, required=STANDIN_COLUMNS, optional=STANDIN_OPTIONAL)]


def _standin_row(row: Row) -> GateRow:
    reading = Reading(
        row.need("text"), row.need("citation_pinyin"), row.need("spoken_pinyin"),
        "phrase", row.get("text_traditional") or None,
    )  # fmt: skip
    return GateRow(row.where, reading, row.get("flag"), row.get("status", "unverified"))


def _shape_problem(r: Reading) -> str | None:
    """Why a reading cannot be a gate phrase at all, if it cannot."""
    try:
        citation, spoken = r.citation(), r.spoken()
    except ValueError as e:
        return str(e)
    if len(citation) != len(spoken):
        return f"citation pinyin has {len(citation)} syllables but spoken pinyin has {len(spoken)}"
    if len(r.text) != len(citation):
        return f"{len(r.text)} characters but {len(citation)} syllables"
    if r.text_traditional is not None and len(r.text_traditional) != len(r.text):
        return "text_traditional is not the same length as text"
    if not 3 <= len(r.text) <= 4:
        return f"a gate phrase is 一 + measure word + noun of 3 or 4 syllables, not {len(r.text)}"
    if r.text[0] != "一" or (citation[0].base, citation[0].tone) != ("yi", "1"):
        return "not a phrase that starts with the numeral 一 (yī)"
    return None


def _correct_card(r: Reading) -> dict:
    return pair_cards("gate", "p", r, r, note="")[0]


def usable_or_left(row: GateRow, lexicon: Lexicon) -> Usable | Left:
    r = row.reading
    if (why := _shape_problem(r)) is not None:
        return Left(row.where, r.text, why)
    if problems := trial.reading_problems(_correct_card(r)):
        return Left(row.where, r.text, f"its own pinyin does not hold: {problems[0]}")

    def accept(error: Reading) -> list[str]:
        return trial.problems(list(pair_cards("gate", "p", r, error, note="")))

    sub, reasons = derive_error(r, lexicon, accept)
    if sub is None:
        return Left(row.where, r.text, "no error word the contract accepts (" + "; ".join(reasons) + ")")
    return Usable(row.where, r, sub, row.flag, row.status)


def build_gate(
    rows: list[GateRow], lexicon: Lexicon, pairs: int, *, earlier_unusable: list[Left] | None = None
) -> GateBuild:
    """The gate cards (`g01-c`, `g01-e`, ...) for `pairs` pairs chosen from `rows`. Raises
    `BuildError`, with the full report, if fewer than `pairs` rows can make a pair."""
    out = GateBuild(unusable=list(earlier_unusable or []))
    usable: list[Usable] = []
    seen: set[str] = set()
    for row in rows:
        if row.reading.text in seen:
            out.unusable.append(Left(row.where, row.reading.text, "the same phrase is in an earlier row"))
            continue
        seen.add(row.reading.text)
        result = usable_or_left(row, lexicon)
        (usable if isinstance(result, Usable) else out.unusable).append(result)  # type: ignore[arg-type]
    out.selected, out.passed_over = select(usable, pairs)
    if len(out.selected) < pairs:
        raise BuildError(
            f"only {len(out.selected)} of {pairs} gate pairs can be made\n" + "\n".join(out.report_lines())
        )
    for i, u in enumerate(out.selected, start=1):
        pair = f"g{i:02d}"
        c, e = pair_cards(
            "gate", pair, u.reading, u.substitution.error, note=u.substitution.variant.note(), status=u.status
        )
        out.cards += [c, e]
        out.flags |= _flags(c["id"], e["id"], u)
    return out


def _flags(correct_id: str, error_id: str, u: Usable) -> dict[str, str]:
    flags = {}
    if u.flag:
        flags[correct_id] = u.flag
    notes = [u.substitution.variant.flag] if u.substitution.variant.flag else []
    if u.substitution.position != len(u.reading.text) - 1:
        notes.append(
            f"the error is in the measure word {u.reading.text[u.substitution.position]}, not the noun "
            "(a changed noun would move its sandhi, R63)"
        )
    if notes:
        flags[error_id] = "; ".join(notes)
    return flags
