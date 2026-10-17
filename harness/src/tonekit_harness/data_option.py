"""`--data DIR`: the data root option of every command that reads or writes the data root
(docs/s05/contracts.md section 3). It is accepted before the command (`tkh --data DIR corpora`)
and after it (`tkh intake --data DIR ...`); the one after the command wins."""

from __future__ import annotations

import argparse
from pathlib import Path

from .contracts.registry import data_root

HELP = "data root (default: $TONEKIT_DATA, else ~/tonekit-data)"


def add_data_option(parser: argparse.ArgumentParser, *, top_level: bool = False) -> None:
    """Add `--data DIR` to `parser`. A command's own option has no default, so it does not hide
    a `--data` given before the command (`top_level`, the `tkh` parser's)."""
    parser.add_argument("--data", metavar="DIR", default=None if top_level else argparse.SUPPRESS, help=HELP)


def root_from(args: argparse.Namespace) -> Path:
    """The data root a command was asked to use: `--data`, else `$TONEKIT_DATA`, else
    `~/tonekit-data`. An empty `--data` raises `RegistryError` (`data_root`) rather than meaning
    the current directory."""
    return data_root(getattr(args, "data", None))
