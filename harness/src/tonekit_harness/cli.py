"""`tkh`: the harness command line.

Each module in MODULES exposes `register(subparsers)`, which adds its subcommand and sets
`func` (a callable taking the parsed args and returning the exit code). To add a subcommand,
add its module to MODULES.
"""

from __future__ import annotations

import argparse

from . import adversary, evaluate, ingest, provenance, synth

MODULES = [ingest, provenance, evaluate, synth, adversary]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tkh", description="tonekit evaluation harness")
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    for module in MODULES:
        module.register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
