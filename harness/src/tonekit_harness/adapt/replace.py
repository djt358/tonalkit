"""Putting a staged corpus in place: a new corpus is one rename; an existing one is left alone when
the new one is the same, file for file, and otherwise swapped in one undoable step (intake's
`commit` pieces), so a reader never sees half of either."""

from __future__ import annotations

import filecmp
from pathlib import Path

from ..intake.commit import MoveNew, apply_all, move_dir_into_place, remove_tree


def _files(root: Path) -> dict[str, Path]:
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}


def same_tree(a: Path, b: Path) -> bool:
    """Whether the directories hold the same files with the same bytes."""
    left, right = _files(a), _files(b)
    if left.keys() != right.keys():
        return False
    return all(filecmp.cmp(left[name], right[name], shallow=False) for name in left)


def put_in_place(staged: Path, corpus: Path, aside: Path) -> str:
    """Move `staged` to `corpus`: `created`, `unchanged` (the staged copy is removed) or
    `replaced` (the old corpus goes through `aside`, which is removed afterwards)."""
    if not (corpus / "corpus.toml").exists():
        move_dir_into_place(staged, corpus)
        return "created"
    if same_tree(staged, corpus):
        remove_tree(staged)
        return "unchanged"
    apply_all([MoveNew(corpus, aside), MoveNew(staged, corpus)])
    try:
        remove_tree(aside)
    except OSError:
        pass  # the new corpus is in place; the next `tkh adapt` of this corpus removes what is left
    return "replaced"
