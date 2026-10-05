"""`tkh intake PATH... [--corpus ID] [--source SRC] [--data DIR] [--deck PATH]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import clearance
from ..contracts.registry import RegistryError
from ..manifest import ManifestError
from ..provenance import ProvenanceError
from ..repo import repo_root
from .errors import IntakeError
from .options import add_data_option, root_from
from .run import IntakeOptions, intake_bundle
from .summary import bundle_lines, next_lines

# What a refused bundle raises; any of these leaves the data root as it was.
REFUSED = (IntakeError, ManifestError, RegistryError, OSError)


def _options(args: argparse.Namespace) -> IntakeOptions:
    return IntakeOptions(
        root=root_from(args),
        repo=repo_root(),
        register=clearance.read_register(None),
        corpus_id=args.corpus,
        source=args.source,
        deck=Path(args.deck) if args.deck else None,
    )


def _run(args: argparse.Namespace) -> int:
    try:
        opts = _options(args)
    except (IntakeError, OSError, ProvenanceError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    results, failed = [], 0
    for path in args.paths:
        try:
            result = intake_bundle(Path(path), opts)
        except REFUSED as e:
            print(f"error: {path}: {e}", file=sys.stderr)
            failed += 1
            continue
        print("\n".join(bundle_lines(result, opts.register)))
        results.append(result)
    if results:
        print("\n".join(next_lines(results, opts.root)))
    return 1 if failed else 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "intake", help="take kit session bundles (zip or unzipped folder) into a corpus under the data root"
    )
    p.add_argument("paths", nargs="+", metavar="PATH", help="a bundle zip, or the folder it unzips to")
    p.add_argument("--corpus", metavar="ID", help="corpus id (default: volunteers-<deck id>)")
    p.add_argument(
        "--source", metavar="SRC", help="data-register.csv id for a new corpus (default: volunteer-corpus)"
    )
    add_data_option(p)
    p.add_argument(
        "--deck",
        metavar="PATH",
        help="the deck JSON the kit served, when neither kit/deck/<id>.json nor its git history has it",
    )
    p.set_defaults(func=_run)
