"""Earlier versions of a deck file from git: a bundle names the sha256 of the deck JSON the phone
fetched, which may be an older commit's file than the one checked out."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from pathlib import Path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)


def file_versions(repo: Path, relpath: str) -> Iterator[tuple[str, bytes]]:
    """Each committed version of `relpath` in `repo`, on any branch, newest first, as (commit,
    bytes). Nothing when git is missing or `repo` is not a git checkout."""
    try:
        log = _git(repo, "log", "--all", "--format=%H", "--", relpath)
    except OSError:  # no git on the PATH
        return
    if log.returncode != 0:
        return
    for commit in log.stdout.decode().split():
        shown = _git(repo, "show", f"{commit}:{relpath}")
        if shown.returncode == 0:  # not when the commit deleted the file
            yield commit, shown.stdout
