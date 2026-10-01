"""`tkh`: the harness command line.

Each module in MODULES exposes `register(subparsers)`, which adds its subcommand and sets
`func` (a callable taking the parsed args and returning the exit code). To add a subcommand,
add its module to MODULES.

The commands that need pyworld (WORLD, built from source on Linux and macOS, so the one
dependency that can be broken on a machine where the rest works) are OPTIONAL_MODULES: they are
imported when the parser is built, not when this module is, and a failure to import one disables
only its own command, with the reason, while every other command keeps working.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable

from . import bakeoff, evaluate, ingest, provenance, schema

MODULES = [ingest, provenance, evaluate, bakeoff, schema]
OPTIONAL_MODULES = ["synth", "adversary"]  # tonekit_harness.<name>; both need pyworld


def _unavailable(command: str, reason: str) -> Callable[[argparse.Namespace], int]:
    def run(args: argparse.Namespace) -> int:
        print(f"error: tkh {command} is unavailable: {reason}", file=sys.stderr)
        return 1

    return run


def _register_optional(subparsers, name: str) -> None:
    try:
        module = importlib.import_module(f".{name}", __package__)
    except Exception as e:  # pyworld missing, built for another platform or against another numpy
        reason = f"cannot import {name} ({type(e).__name__}: {e}); the other commands still work"
        # argparse %-formats help text, and the reason may hold a `%` (a Windows error's "%1")
        help_text = f"unavailable: {reason}".replace("%", "%%")
        p = subparsers.add_parser(name, help=help_text, add_help=False)
        p.set_defaults(func=_unavailable(name, reason), unavailable=True)
    else:
        module.register(subparsers)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tkh", description="tonekit evaluation harness")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for module in MODULES:
        module.register(subparsers)
    for name in OPTIONAL_MODULES:
        _register_optional(subparsers, name)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    # An unavailable command takes whatever arguments it was meant to: it only reports why not.
    args, extra = parser.parse_known_args(argv)
    if extra and not getattr(args, "unavailable", False):
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    return args.func(args)
