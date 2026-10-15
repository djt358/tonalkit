"""`tkh adapt {aishell3,thchs30} SRC [--data DIR] [--corpus ID] [--max-syllables N]
[--limit-speakers N] [--register CSV]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import clearance
from ..contracts.registry import RegistryError
from ..intake.errors import IntakeError
from ..intake.options import add_data_option, root_from
from ..manifest import ManifestError
from ..provenance import ProvenanceError
from ..repo import repo_root
from . import aishell3, thchs30
from .corpus_files import AdaptError
from .run import DEFAULT_MAX_SYLLABLES, AdaptOptions, adapt
from .summary import next_lines, result_lines

ADAPTERS = {m.NAME: m for m in (aishell3, thchs30)}
# What a refused run raises; any of these leaves the data root as it was.
REFUSED = (AdaptError, IntakeError, ManifestError, RegistryError, ProvenanceError, OSError)


def _run(args: argparse.Namespace) -> int:
    try:
        opts = AdaptOptions(
            root=root_from(args),
            repo=repo_root(),
            register=clearance.read_register(args.register),
            corpus_id=args.corpus,
            max_syllables=args.max_syllables,
            limit_speakers=args.limit_speakers,
        )
        result = adapt(ADAPTERS[args.adapter], Path(args.src), opts)
    except REFUSED as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print("\n".join(result_lines(result) + next_lines(result, opts.root)))
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "adapt",
        help="turn a downloaded public corpus (AISHELL-3, THCHS-30) into a corpus under the data root",
    )
    p.add_argument("adapter", choices=sorted(ADAPTERS), help="which corpus SRC is")
    p.add_argument("src", metavar="SRC", help="the extracted download (data_aishell3/ or data_thchs30/)")
    add_data_option(p)
    p.add_argument("--corpus", metavar="ID", help="corpus id (default: the adapter's name)")
    p.add_argument(
        "--max-syllables",
        type=int,
        default=DEFAULT_MAX_SYLLABLES,
        metavar="N",
        help=f"drop utterances longer than this (default {DEFAULT_MAX_SYLLABLES}, ruling R123)",
    )
    p.add_argument(
        "--limit-speakers",
        type=int,
        metavar="N",
        help="adapt only the first N speakers by id (a quick trial; default: every speaker)",
    )
    p.add_argument(
        "--register", metavar="CSV", help="data register (default: data-register.csv at the repository root)"
    )
    p.set_defaults(func=_run)
