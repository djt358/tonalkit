"""A corpus's manifest rows, read with the manifest loader and joined to the corpus's speakers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from ..contracts.registry import CorpusMeta, RegistryError, Speaker
from ..manifest import Clip, ManifestError
from ..manifest import load as load_manifest
from .errors import reason
from .items import CorpusClip

MAX_PROBLEMS_SHOWN = 10


class RowProblem(NamedTuple):
    row: int  # index among the manifest's rows
    text: str
    first_row: int | None = None  # for a repeated clip id: the row that used it first


def corpus_clips(
    meta: CorpusMeta, speakers: Mapping[str, Speaker], manifest_path: Path
) -> tuple[CorpusClip, ...]:
    """The clips of the manifest at `manifest_path`, each with its corpus and `[[speaker]]`.

    Raises `RegistryError` naming the file (and the line of every row at fault, up to
    `MAX_PROBLEMS_SHOWN`) if the manifest is missing or unreadable, a clip names a speaker the
    corpus does not have, a clip's source is not the corpus's, a clip id is used twice, or a clip's
    path leaves the corpus directory."""
    clips = _read(manifest_path, meta)
    problems = row_problems(clips, meta, speakers)
    if problems:
        raise RegistryError(_describe(manifest_path, meta, problems))
    return tuple(
        CorpusClip(meta, speakers[c.speaker], c, manifest_path.parent / c.path) for c in clips
    )


def _read(manifest_path: Path, meta: CorpusMeta) -> list[Clip]:
    if not manifest_path.is_file():
        raise RegistryError(
            f"{manifest_path}: no such manifest (corpus {meta.id!r} names manifest = {meta.manifest!r})"
        )
    try:
        return load_manifest(manifest_path)
    except ManifestError as e:  # starts with <path>:<line>:
        raise RegistryError(str(e)) from e
    except (OSError, UnicodeDecodeError) as e:
        raise RegistryError(f"{manifest_path}: cannot read the manifest: {reason(e)}") from e


def row_problems(clips: list[Clip], meta: CorpusMeta, speakers: Mapping[str, Speaker]) -> list[RowProblem]:
    """Every row that cannot be joined to the corpus, in manifest order."""
    problems: list[RowProblem] = []
    first_row: dict[str, int] = {}
    for row, clip in enumerate(clips):
        if clip.speaker not in speakers:
            who = f"clip {clip.id!r}: speaker {clip.speaker!r}"
            problems.append(RowProblem(row, f"{who} is not a [[speaker]] of the corpus"))
        if clip.source != meta.source:
            problems.append(
                RowProblem(
                    row,
                    f"clip {clip.id!r}: source {clip.source!r} is not the corpus's source {meta.source!r} "
                    "(one corpus has one data-register source)",
                )
            )
        if clip.id in first_row:
            problems.append(RowProblem(row, f"clip id {clip.id!r} is used twice", first_row[clip.id]))
        else:
            first_row[clip.id] = row
        path = PurePosixPath(clip.path)
        if path.is_absolute() or ".." in path.parts:
            problems.append(
                RowProblem(
                    row,
                    f"clip {clip.id!r}: path {clip.path!r} must be relative, with no '..' "
                    "(audio lives inside the corpus directory)",
                )
            )
    return problems


def _describe(manifest_path: Path, meta: CorpusMeta, problems: list[RowProblem]) -> str:
    lines = _row_lines(manifest_path)
    shown = []
    for p in problems[:MAX_PROBLEMS_SHOWN]:
        again = "" if p.first_row is None else f" (first on line {lines[p.first_row]})"
        shown.append(f"{manifest_path}:{lines[p.row]}: {p.text}{again}")
    if len(problems) > MAX_PROBLEMS_SHOWN:
        shown.append(f"{manifest_path}: and {len(problems) - MAX_PROBLEMS_SHOWN} more problems")
    return f"corpus {meta.id!r}: invalid manifest\n" + "\n".join(f"  {s}" for s in shown)


def _row_lines(path: Path) -> list[int]:
    """The line number of each row: `manifest.load` skips blank lines, so row i is the i-th
    non-blank line."""
    with path.open(encoding="utf-8") as f:
        return [n for n, line in enumerate(f, start=1) if line.strip()]
