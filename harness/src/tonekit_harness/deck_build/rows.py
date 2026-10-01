"""Reading the CSV sources of the deck: UTF-8 (a spreadsheet's BOM is fine), a header row, one
record per line. Values are stripped, blank lines skipped. A problem names the file and the line."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import BuildError


@dataclass(frozen=True)
class Row:
    path: Path
    line: int  # the line of the record in the file (the header is line 1)
    values: Mapping[str, str]

    @property
    def where(self) -> str:
        return f"{self.path.name}:{self.line}"

    def get(self, column: str, default: str = "") -> str:
        return self.values.get(column) or default

    def need(self, column: str) -> str:
        """The value of a column that must not be empty."""
        value = self.get(column)
        if not value:
            raise BuildError(f"{self.where}: {column} is empty")
        return value


def read_rows(
    path: str | Path,
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
    strict: bool = True,
) -> list[Row]:
    """The records of the CSV at `path`. `required` columns must be in the header. With `strict`,
    a column outside `required` and `optional` is an error (a misspelt header must not silently
    drop data); without it other columns are ignored (someone else's table)."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise BuildError(f"{path}: cannot read: {e.strerror or e}") from e
    reader = csv.DictReader(text.splitlines())
    header = [h.strip() for h in reader.fieldnames or []]
    missing = [c for c in required if c not in header]
    if missing:
        raise BuildError(f"{path}: missing column(s) {', '.join(missing)} (header has: {', '.join(header)})")
    unknown = [c for c in header if c not in {*required, *optional}]
    if strict and unknown:
        raise BuildError(f"{path}: unknown column(s) {', '.join(unknown)} (known: {', '.join([*required, *optional])})")
    rows = []
    for record in reader:
        if None in record:  # more fields than the header
            raise BuildError(f"{path}:{reader.line_num}: more values than the header has columns")
        values = {k.strip(): (v or "").strip() for k, v in record.items()}
        if any(values.values()):
            rows.append(Row(path, reader.line_num, values))
    return rows
