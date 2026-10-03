"""`tkh deck build`, `tkh deck approve` and `tkh deck check`: the prompt deck (docs/s05/contracts.md
section 1)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .contracts.deck import DeckError
from .deck_build.approvals import FILE as APPROVALS, merge, read_approvals, write_approvals
from .deck_build.approve import decisions
from .deck_build.assemble import Built, build_deck
from .deck_build.audit import audit_markdown
from .deck_build.check_report import load_any, problem_report, ship_report, summary
from .deck_build.emit import write_deck
from .deck_build.errors import BuildError
from .deck_build.ship_check import ship_problems
from .repo import repo_root


def _deck_dir() -> Path:
    return repo_root() / "kit" / "deck"


def _sources(args: argparse.Namespace) -> Path:
    return Path(args.sources) if args.sources else _deck_dir() / "sources"


def _field_map(items: list[str]) -> dict[str, str]:
    out = {}
    for item in items:
        field, sep, column = item.partition("=")
        if not sep or not field or not column:
            raise BuildError(f"--gmeasure-map wants FIELD=COLUMN, not {item!r}")
        out[field] = column
    return out


def _built(args: argparse.Namespace, *, approvals: bool) -> Built:
    return build_deck(
        _sources(args),
        gmeasure=args.gmeasure,
        gmeasure_map=_field_map(args.gmeasure_map),
        gate_pairs=args.gate_pairs,
        approvals=approvals,
    )


def _build(args: argparse.Namespace) -> int:
    try:
        built = _built(args, approvals=True)
    except (BuildError, DeckError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else _deck_dir()
    paths = write_deck(built.data, out)
    audit = Path(args.audit) if args.audit else out / f"{built.data['deck']['id']}.audit.md"
    audit.write_text(audit_markdown(built.data, built.flags, built.gate.source), encoding="utf-8")
    for path in [*paths, audit]:
        print(f"wrote {path}")
    print(f"{len(built.data['card'])} cards")
    for line in built.report_lines():
        print(line)
    return 0


def _approve(args: argparse.Namespace) -> int:
    path = _sources(args) / APPROVALS
    try:
        every = _built(args, approvals=False).data["card"]  # every card as the sources make it
        deck = _built(args, approvals=True).data["card"] if args.all else every  # without the rejected ones
        rows = decisions(every, deck, args.ids, everything=args.all, rejected=args.reject, note=args.note)
        write_approvals(path, merge(read_approvals(path), rows))
    except (BuildError, DeckError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    word = "rejected" if args.reject else "approved"
    print(f"{word} {len(rows)} card{'' if len(rows) == 1 else 's'} in {path}")
    print("run `tkh deck build` to mark them in the deck files")
    return 0


def _check(args: argparse.Namespace) -> int:
    path = Path(args.path)
    try:
        deck = load_any(path, args.pack)
    except DeckError as e:
        print(f"FAIL {problem_report(e)}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"error: cannot read {path}: {e.strerror or e}", file=sys.stderr)
        return 1
    if args.ship and (problems := ship_problems(deck)):
        print(ship_report(path, problems), file=sys.stderr)
        return 1
    print(summary(deck, path))
    if args.ship:
        print("  ready to ship: every card approved, every pair and set whole")
    return 0


def _build_options(p: argparse.ArgumentParser) -> None:
    p.add_argument("--sources", metavar="DIR", help="the CSV sources (default: kit/deck/sources)")
    p.add_argument("--gmeasure", metavar="CSV", help="take the gate phrases from DJ's g_measure table")
    p.add_argument(
        "--gmeasure-map", metavar="FIELD=COLUMN", action="append", default=[],
        help="which column of the g_measure table holds a field (text, citation_pinyin, spoken_pinyin, "
        "text_traditional, measure, word); repeatable",
    )  # fmt: skip
    p.add_argument("--gate-pairs", type=int, default=20, metavar="N", help="gate pairs to choose (default 20)")


def register(subparsers) -> None:
    p = subparsers.add_parser("deck", help="build the prompt deck from its CSV sources, approve cards, or check a deck file")
    actions = p.add_subparsers(dest="deck_action", required=True, metavar="ACTION")

    b = actions.add_parser("build", help="sources (kit/deck/sources) -> kit/deck/<id>.toml, .json and .audit.md")
    _build_options(b)
    b.add_argument("--out", metavar="DIR", help="where to write the deck and its audit sheet (default: kit/deck)")
    b.add_argument("--audit", metavar="PATH", help="write the audit sheet here instead of next to the deck")
    b.set_defaults(func=_build)

    a = actions.add_parser(
        "approve", help="record DJ's audit in the sources' approvals.csv, pinned to each card's fingerprint (R91)"
    )
    _build_options(a)
    a.add_argument("ids", nargs="*", metavar="ID", help="the cards to approve (g01-c, r03, ...)")
    a.add_argument("--all", action="store_true", help="every card the built deck has (not the ones that stand rejected)")
    a.add_argument("--reject", action="store_true", help="record a rejection instead; the builder then drops the card")
    a.add_argument("--note", default="", metavar="TEXT", help="a note to keep with the rows")
    a.set_defaults(func=_approve)

    c = actions.add_parser("check", help="validate a deck file (TOML, or the kit's JSON) against the contract")
    c.add_argument("path", metavar="PATH")
    c.add_argument("--pack", metavar="TOML", help="the pack whose tone ids apply (default: packs/cmn/cmn.toml)")
    c.add_argument(
        "--ship", action="store_true",
        help="also fail unless every card is approved, every pair and minimal set is whole and the register has 8 cards",
    )  # fmt: skip
    c.set_defaults(func=_check)
