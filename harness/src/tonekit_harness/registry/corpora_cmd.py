"""`tkh corpora`: the corpora under the data root."""

from __future__ import annotations

import argparse
import sys

from .options import data_root_from
from .summary import CorpusSummary, summarise

HEADER = ["corpus", "kind", "source", "speakers", "clips", "stale"]


def format_table(summaries: list[CorpusSummary]) -> str:
    """One row per corpus: id, kind, source, speakers per split, clips per set, stale flag."""
    rows = [HEADER] + [_row(s) for s in summaries]
    widths = [max(len(r[c]) for r in rows) for c in range(len(HEADER))]
    return "\n".join("  ".join(cell.ljust(w) for cell, w in zip(r, widths, strict=True)).rstrip() for r in rows)


def _row(s: CorpusSummary) -> list[str]:
    stale = "-" if s.error else ("STALE" if s.stale else "no")
    return [s.id, s.kind or "?", s.source or "?", _counts(s.speakers, s.error), _counts(s.clips, s.error), stale]


def _counts(counts: dict[str, int], error: str | None) -> str:
    if not counts:
        return "?" if error else "-"
    return ", ".join(f"{name} {n}" for name, n in counts.items())


def _run(args: argparse.Namespace) -> int:
    root = data_root_from(args)
    if not root.path.is_dir():
        print(f"error: the data root {root.path} does not exist (set TONEKIT_DATA or pass --data)", file=sys.stderr)
        return 1
    print(f"data root: {root.path}")
    summaries = [summarise(root, corpus_id) for corpus_id in root.corpus_ids()]
    if not summaries:
        print(f"no corpora under {root.corpora_dir}")
        return 0
    print(format_table(summaries))
    for s in summaries:
        if s.stale:
            print(f"stale: {s.id}: " + "; ".join(r.reason for r in s.stale.reasons))
    broken = [s for s in summaries if s.error]
    for s in broken:
        print(f"error: {s.error}", file=sys.stderr)
    return 1 if broken else 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "corpora",
        help="list the corpora under the data root: kind, source, speakers per split, clips per set, stale",
    )
    p.set_defaults(func=_run)
