"""Moving a staged session into a corpus as one change: each step can be undone, and a failure
undoes the steps before it, so a corpus never keeps half a session."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from ..atomic import write_text_atomic


def _make_parents(path: Path) -> list[Path]:
    """Create the missing parent directories of `path`; returns them, outermost first."""
    made = [p for p in reversed(path.parents) if not p.exists()]
    for p in made:
        p.mkdir()
    return made


def _remove_made(made: list[Path]) -> None:
    for p in reversed(made):
        p.rmdir()


@dataclass
class MoveNew:
    """Move `src` to `dst`, which must not exist; parent directories are created (and removed
    again by `undo`)."""

    src: Path
    dst: Path
    made: list[Path] = field(default_factory=list)

    def do(self) -> None:
        if self.dst.exists():
            raise FileExistsError(f"{self.dst} already exists")
        self.made = _make_parents(self.dst)
        os.rename(self.src, self.dst)

    def undo(self) -> None:
        os.rename(self.dst, self.src)
        _remove_made(self.made)


@dataclass
class Replace:
    """Put `src` in place of `dst` (which may not exist yet; parent directories are created);
    `undo` restores the old file."""

    src: Path
    dst: Path
    before: str | None = None
    made: list[Path] = field(default_factory=list)

    def do(self) -> None:
        self.before = self.dst.read_text(encoding="utf-8") if self.dst.exists() else None
        self.made = _make_parents(self.dst)
        os.replace(self.src, self.dst)

    def undo(self) -> None:
        if self.before is None:
            self.dst.unlink(missing_ok=True)
            _remove_made(self.made)
        else:
            write_text_atomic(self.dst, self.before)


def apply_all(steps: list[MoveNew | Replace]) -> None:
    """Do `steps` in order; if one fails, undo the ones done (newest first) and re-raise."""
    done: list[MoveNew | Replace] = []
    try:
        for step in steps:
            step.do()
            done.append(step)
    except BaseException as e:
        for step in reversed(done):
            try:
                step.undo()
            except OSError as undo_error:
                e.add_note(f"could not undo a step ({undo_error}); `tkh purge --session` removes what is left")
        raise


def move_dir_into_place(src: Path, dst: Path) -> None:
    """A whole new directory (a new corpus): one rename. `dst` must be absent or empty."""
    if dst.exists():
        dst.rmdir()  # empty: checked by the caller; raises if it is not
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.rename(src, dst)


def remove_tree(path: Path) -> int:
    """Delete `path` (a file or a directory) and return how many files went."""
    if path.is_dir() and not path.is_symlink():
        count = sum(1 for p in path.rglob("*") if p.is_file() or p.is_symlink())
        shutil.rmtree(path)
        return count
    path.unlink()
    return 1
