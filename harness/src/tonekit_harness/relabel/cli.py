"""`tkh relabel FILE --corpus ID [--data DIR]`: apply the review page's export to the corpus."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import clearance
from ..contracts.registry import RegistryError
from ..contracts.relabel import RelabelError, load_export
from ..data_option import add_data_option, root_from
from ..intake.errors import IntakeError
from ..intake.packs import pack_path
from ..provenance import ProvenanceError
from ..repo import repo_root
from .apply import relabel_corpus
from .summary import next_lines, outcome_lines


def _run(args: argparse.Namespace) -> int:
    path = Path(args.file)
    repo = repo_root()
    try:
        root = root_from(args)
        export = load_export(path)
        outcome = relabel_corpus(
            root,
            args.corpus,
            export,
            repo=repo,
            register=clearance.read_register(None),
            source=path.name,
        )
    except (RelabelError, IntakeError, RegistryError, ProvenanceError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\n".join(outcome_lines(outcome, path.name, export.who, len(export.decisions))))
    if outcome.plan.changes:
        print("\n".join(next_lines(outcome, pack_path(repo, outcome.state.lect), root)))
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "relabel",
        help="apply what you heard on the tkh review page (its relabels-<corpus>.json) to the corpus manifest",
    )
    p.add_argument("file", metavar="FILE", help="the relabels-<corpus>.json the review page downloaded")
    p.add_argument("--corpus", required=True, metavar="ID", help="the corpus the file is for")
    add_data_option(p)
    p.set_defaults(func=_run)
