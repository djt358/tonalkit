"""`--select CORPUS_GLOB[:SPLIT[,SPLIT]]`: how `tkh eval` and `tkh fit` name the clips they read
from the data root instead of one manifest. Repeatable; the selections compose into one (a union
across corpora, `Selection.__or__`):

    tkh fit --select 'aishell3:calib' --select 'volunteers-*:calib' ...
    tkh eval --select 'volunteers-*:gate,dev' ...

A corpus id (no `*?[`) must exist; every selector must select at least one clip, so a typo never
selects nothing. Without `:SPLIT` a selector takes the command's default splits (eval: every split;
fit: `calib`).
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import get_args

from ..contracts.registry import Split
from .errors import SelectionError
from .select import GLOB_CHARACTERS, match_corpora
from .selection import Selection

SYNTAX = "CORPUS_GLOB[:SPLIT[,SPLIT]]"
SPLITS: tuple[str, ...] = get_args(Split)


@dataclass(frozen=True)
class Selector:
    """One `--select`: corpus ids or a glob, and the speaker splits (None: the command's default)."""

    text: str
    corpora: str
    splits: tuple[Split, ...] | None = None


def parse_selector(text: str) -> Selector:
    """`aishell3`, `volunteers-*:calib`, `aishell3:calib,dev`. Raises `SelectionError` saying what
    is wrong."""
    corpora, colon, rest = text.partition(":")
    corpora = corpora.strip()
    if not corpora:
        raise SelectionError(f"--select {text!r}: no corpus id or glob ({SYNTAX})")
    if not colon:
        return Selector(text, corpora)
    splits = [s.strip() for s in rest.split(",")]
    if not all(splits):
        raise SelectionError(f"--select {text!r}: an empty split ({SYNTAX}, e.g. aishell3:calib,dev)")
    unknown = [s for s in splits if s not in SPLITS]
    if unknown:
        raise SelectionError(f"--select {text!r}: unknown split {', '.join(unknown)} (known: {', '.join(SPLITS)})")
    return Selector(text, corpora, tuple(dict.fromkeys(splits)))  # type: ignore[arg-type]


def selector_argument(text: str) -> Selector:
    """`parse_selector` as an argparse `type`: a malformed `--select` is a usage error."""
    try:
        return parse_selector(text)
    except SelectionError as e:
        raise argparse.ArgumentTypeError(str(e)) from e


def add_select_option(parser: argparse._ActionsContainer, default_splits: str) -> None:
    parser.add_argument(
        "--select",
        action="append",
        type=selector_argument,
        metavar=SYNTAX,
        help=f"clips from the corpora under the data root instead of one manifest (repeatable; the selections "
        f"compose; speakers are named corpus/speaker); without :SPLIT, {default_splits}",
    )


def compose(root, selectors: Sequence[Selector], *, default_splits: Sequence[Split] | None = None) -> Selection:
    """The union of every selector's clips under the data root `root` (a `DataRoot`). Raises
    `SelectionError` for no selector, a corpus id that is not there or a selector that selects no
    clip, and `RegistryError` for a corpus that cannot be loaded."""
    if not selectors:
        raise SelectionError(f"no --select given ({SYNTAX})")
    out = Selection(root.corpora_dir)
    for s in selectors:
        splits = s.splits if s.splits is not None else default_splits
        chosen = root.select([s.corpora], splits=splits)
        if not chosen:
            raise SelectionError(f"--select {s.text!r} selects no clips: {_nothing(root, s.corpora, splits)}")
        out = out | chosen
    return out


def _nothing(root, pattern: str, splits: Sequence[str] | None) -> str:
    ids = root.corpus_ids()
    matched = match_corpora([pattern], ids)
    if not matched:
        kind = "glob" if GLOB_CHARACTERS & set(pattern) else "id"
        return f"no corpus matches the {kind} {pattern!r} (corpora: {', '.join(ids) or 'none'})"
    where = ", ".join(matched)
    if splits is None:
        return f"{where} {'has' if len(matched) == 1 else 'have'} no clips"
    return f"{where} {'has' if len(matched) == 1 else 'have'} no clips of a speaker in split {', '.join(splits)}"
