"""`tkh --data PATH`: the one option every command that reads data shares."""

from __future__ import annotations

import argparse

from .root import DataRoot


def add_data_option(parser: argparse.ArgumentParser) -> None:
    """Add `--data PATH` to the top-level parser (before the command: `tkh --data PATH corpora`)."""
    parser.add_argument(
        "--data",
        metavar="PATH",
        help="the data root (default: $TONEKIT_DATA, else ~/tonekit-data) for commands that read data",
    )


def data_root_from(args: argparse.Namespace) -> DataRoot:
    """The data root a command was asked to use: `--data`, else `$TONEKIT_DATA`, else the default."""
    return DataRoot(getattr(args, "data", None))
