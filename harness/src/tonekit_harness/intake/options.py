"""The `--data DIR` option of intake and purge (docs/s05/contracts.md section 3)."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..contracts.registry import data_root
from .errors import IntakeError


def add_data_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--data", metavar="DIR", help="data root (default: $TONEKIT_DATA, else ~/tonekit-data)")


def root_from(args: argparse.Namespace) -> Path:
    """The data root; an empty `--data` is refused rather than meaning the current directory."""
    if args.data is not None and not str(args.data).strip():
        raise IntakeError("--data is empty; give a directory, or leave it out for $TONEKIT_DATA")
    return data_root(args.data)
