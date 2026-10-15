"""`tkh review --corpus ID [--data DIR] [--speaker S] [--set S] [--results PATH] [--deck PATH]`:
write the listening page for a corpus under the data root and say how to open it."""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path

from ..contracts.registry import RegistryError
from ..contracts.relabel import RelabelError
from ..data_option import add_data_option, root_from
from ..intake import layout
from ..intake.errors import IntakeError
from ..repo import repo_root
from .cards import ReviewError
from .page import write_page
from .scorer import DISAGREES, TWIN
from .view import ReviewOptions, page_data


def _options(args: argparse.Namespace) -> ReviewOptions:
    return ReviewOptions(
        root=root_from(args),
        corpus_id=args.corpus,
        repo=repo_root(),
        results=Path(args.results) if args.results else None,
        deck=Path(args.deck) if args.deck else None,
        speakers=tuple(args.speaker or ()),
        sets=tuple(args.set or ()),
    )


def _lines(path: Path, data: dict, opts: ReviewOptions) -> list[str]:
    clips = data["clips"]
    twin = sum(c["group"] == TWIN for c in clips)
    disagree = sum(c["group"] == DISAGREES for c in clips)
    lines = [
        f"review {opts.corpus_id}: {len(clips)} clips; first the {twin} where the scorer hears the twin card's "
        f"reading, then the {disagree} where it otherwise disagrees with the card"
    ]
    if data["results"] is None:
        results = layout.results_path(opts.root, opts.corpus_id)
        lines.append(f"  no scorer view yet: run tkh eval with --results {results}, then tkh review again")
    cid = shlex.quote(opts.corpus_id)
    relabel = f"uv run tkh relabel ~/Downloads/relabels-{opts.corpus_id}.json --corpus {cid} --data {shlex.quote(str(opts.root))}"
    return lines + [
        f"  page: {path}",
        f"  open it in a browser on this computer: {path.as_uri()}",
        "  it links the volunteers' audio, so it stays under the data root: never copy or publish it",
        f"  when you have exported your decisions, from harness/: {relabel}",
    ]


def _run(args: argparse.Namespace) -> int:
    try:
        opts = _options(args)
        data = page_data(opts)
        path = write_page(opts.root, opts.corpus_id, data)
    except (ReviewError, RelabelError, IntakeError, RegistryError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\n".join(_lines(path, data, opts)))
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "review", help="write a local page to listen to a corpus's clips and record what was said (then tkh relabel)"
    )
    p.add_argument("--corpus", required=True, metavar="ID", help="the corpus to review")
    add_data_option(p)
    p.add_argument("--speaker", action="append", metavar="S", help="only this speaker (id or session code); repeatable")
    p.add_argument("--set", action="append", metavar="S", help="only this card set (gate, diag_t23, ...); repeatable")
    p.add_argument(
        "--results",
        metavar="PATH",
        help="a tkh eval --results file, the scorer's view "
        "(default: reports/<corpus>.results.json under the data root, if it is there)",
    )
    p.add_argument("--deck", metavar="PATH", help="the deck JSON the kit served, when the repository lacks it (as for intake)")
    p.set_defaults(func=_run)
