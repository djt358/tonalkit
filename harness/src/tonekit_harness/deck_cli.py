"""`tkh deck build` and `tkh deck check`: the prompt deck (docs/s05/contracts.md section 1)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .contracts.deck import DeckError
from .deck_build.assemble import build_deck
from .deck_build.audit import audit_markdown
from .deck_build.check_report import load_any, problem_report, summary
from .deck_build.emit import write_deck
from .deck_build.errors import BuildError
from .repo import repo_root


def _deck_dir() -> Path:
    return repo_root() / "kit" / "deck"


def _field_map(items: list[str]) -> dict[str, str]:
    out = {}
    for item in items:
        field, sep, column = item.partition("=")
        if not sep or not field or not column:
            raise BuildError(f"--gmeasure-map wants FIELD=COLUMN, not {item!r}")
        out[field] = column
    return out


def _build(args: argparse.Namespace) -> int:
    sources = Path(args.sources) if args.sources else _deck_dir() / "sources"
    try:
        built = build_deck(
            sources,
            gmeasure=args.gmeasure,
            gmeasure_map=_field_map(args.gmeasure_map),
            gate_pairs=args.gate_pairs,
        )
    except (BuildError, DeckError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    paths = write_deck(built.data, args.out or _deck_dir())
    if args.audit:
        Path(args.audit).write_text(audit_markdown(built.data, built.flags), encoding="utf-8")
    for path in paths:
        print(f"wrote {path}")
    if args.audit:
        print(f"wrote {args.audit}")
    print(f"{len(built.data['card'])} cards")
    for line in built.report_lines():
        print(line)
    return 0


def _check(args: argparse.Namespace) -> int:
    path = Path(args.path)
    try:
        deck = load_any(path, args.pack)
    except DeckError as e:
        print(f"FAIL {problem_report(e)}", file=sys.stderr)
        return 1
    print(summary(deck, path))
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("deck", help="build the prompt deck from its CSV sources, or check a deck file")
    actions = p.add_subparsers(dest="deck_action", required=True, metavar="ACTION")

    b = actions.add_parser("build", help="sources (kit/deck/sources) -> kit/deck/<id>.toml and .json")
    b.add_argument("--sources", metavar="DIR", help="the CSV sources (default: kit/deck/sources)")
    b.add_argument("--out", metavar="DIR", help="where to write the deck (default: kit/deck)")
    b.add_argument("--gmeasure", metavar="CSV", help="take the gate phrases from DJ's g_measure table")
    b.add_argument(
        "--gmeasure-map", metavar="FIELD=COLUMN", action="append", default=[],
        help="which column of the g_measure table holds a field (text, citation_pinyin, spoken_pinyin, "
        "text_traditional, measure, word); repeatable",
    )  # fmt: skip
    b.add_argument("--gate-pairs", type=int, default=20, metavar="N", help="gate pairs to choose (default 20)")
    b.add_argument("--audit", metavar="PATH", help="also write the audit sheet (markdown) here")
    b.set_defaults(func=_build)

    c = actions.add_parser("check", help="validate a deck file (TOML, or the kit's JSON) against the contract")
    c.add_argument("path", metavar="PATH")
    c.add_argument("--pack", metavar="TOML", help="the pack whose tone ids apply (default: packs/cmn/cmn.toml)")
    c.set_defaults(func=_check)
