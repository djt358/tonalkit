"""A session bundle unzipped into a folder (AirDrop and Finder unzip the kit's zip on a Mac): the
same members as the zip, read from disk. The operating system adds metadata that is not part of
the bundle (Finder's `.DS_Store`, `._*` AppleDouble files, a `__MACOSX` folder); it is left out,
and anything else is a member that `read_bundle` checks like a member of the zip."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path, PurePosixPath

_OS_METADATA_DIRS = frozenset({"__MACOSX"})


def is_os_metadata(name: str) -> bool:
    """True for a member path the operating system added: a part that starts with "." or is a
    `__MACOSX` folder."""
    return any(part.startswith(".") or part in _OS_METADATA_DIRS for part in PurePosixPath(name).parts)


def folder_members(folder: Path) -> dict[str, bytes]:
    """Every file below `folder` by its POSIX path relative to it, sorted, OS metadata left out."""
    members: dict[str, bytes] = {}
    for p in sorted(folder.rglob("*")):
        name = p.relative_to(folder).as_posix()
        if p.is_file() and not is_os_metadata(name):
            members[name] = p.read_bytes()
    return members


def zip_folder(folder: Path) -> zipfile.ZipFile:
    """An in-memory zip of `folder_members(folder)`, for `read_bundle` to check like the kit's zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in folder_members(folder).items():
            z.writestr(name, data)
    return zipfile.ZipFile(buf)
