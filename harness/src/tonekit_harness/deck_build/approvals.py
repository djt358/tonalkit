"""DJ's audit as data: `kit/deck/sources/approvals.csv` (R91), columns `card_id, fingerprint,
decision, note`, decision `approved` or `rejected`. A row pins a decision to what the card showed
(its fingerprint); `tkh deck approve` writes it, `approval_apply` reads it. Rows keep their order in
the file, so a rewrite changes only the rows that changed."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import BuildError
from .fingerprint import LENGTH
from .rows import read_rows

FILE = "approvals.csv"
COLUMNS = ["card_id", "fingerprint", "decision", "note"]
DECISIONS = ("approved", "rejected")
_FINGERPRINT = re.compile(rf"[0-9a-f]{{{LENGTH}}}")


@dataclass(frozen=True)
class Approval:
    card_id: str
    fingerprint: str
    decision: str  # approved | rejected
    note: str = ""
    where: str = ""  # file:line, for reports; empty for a row not read from a file


def read_approvals(path: str | Path) -> list[Approval]:
    """The rows of the approvals file; a missing file is no approvals. A bad decision or fingerprint,
    or a card listed twice, is an error naming the line."""
    path = Path(path)
    if not path.exists():
        return []
    out: list[Approval] = []
    seen: dict[str, str] = {}
    for row in read_rows(path, required=COLUMNS):
        card_id, fingerprint, decision = row.need("card_id"), row.need("fingerprint"), row.need("decision")
        if decision not in DECISIONS:
            raise BuildError(f"{row.where}: decision must be approved or rejected, not {decision!r}")
        if not _FINGERPRINT.fullmatch(fingerprint):
            raise BuildError(f"{row.where}: fingerprint must be {LENGTH} lowercase hex digits, not {fingerprint!r}")
        if card_id in seen:
            raise BuildError(f"{row.where}: {card_id} is already listed at {seen[card_id]}; one row per card")
        seen[card_id] = row.where
        out.append(Approval(card_id, fingerprint, decision, row.get("note"), row.where))
    return out


def merge(existing: list[Approval], new: list[Approval]) -> list[Approval]:
    """`existing` with the rows of `new` replacing the same card's row in place; the rest of `new`
    follows, in its order."""
    by_id = {a.card_id: a for a in new}
    merged = [by_id.pop(a.card_id, a) for a in existing]
    return merged + list(by_id.values())


def approvals_text(approvals: list[Approval]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for a in approvals:
        writer.writerow([a.card_id, a.fingerprint, a.decision, a.note])
    return out.getvalue()


def write_approvals(path: str | Path, approvals: list[Approval]) -> None:
    Path(path).write_bytes(approvals_text(approvals).encode("utf-8"))
