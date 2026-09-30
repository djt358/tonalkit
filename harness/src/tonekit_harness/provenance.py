"""Data-provenance check: every PROVENANCE.toml source must be cleared by data-register.csv, and
every data file in a pack must be attested by the pack's PROVENANCE.toml."""

from __future__ import annotations

import argparse
import csv
import difflib
import os
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

_VALUES = {"allow", "verify", "deny", "n/a"}
_TOP_LEVEL_KEYS = ("artifact", "artifacts", "note", "source", "signoff")
_MANIFEST_NAME = "PROVENANCE.toml"
_DATA_SUFFIXES = {".toml", ".json"}  # the pack's data files: the pack itself and its calibrations


class ProvenanceError(ValueError):
    """The register itself is unusable (as opposed to a manifest violating it)."""


def load_register(register_csv: Path) -> dict[str, str]:
    """data-register.csv as {id: shipped_weights_training}, the column that says whether a dataset
    may be used (`allow`), needs a sign-off (`verify`) or may not (`deny`). Raises
    `ProvenanceError` if the file cannot be used as a register, `OSError` if it cannot be opened."""
    try:
        return _read_register(Path(register_csv))
    except (UnicodeDecodeError, csv.Error) as e:
        # Decoding and parsing happen while the rows are read, so they surface here, not at open().
        raise ProvenanceError(f"{register_csv}: cannot read the register: {e}") from e


def _read_register(register_csv: Path) -> dict[str, str]:
    with register_csv.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = {"id", "shipped_weights_training"} - set(reader.fieldnames or [])
        if missing:
            raise ProvenanceError(f"{register_csv}: missing column(s) {', '.join(sorted(missing))}")
        register: dict[str, str] = {}
        for row in reader:
            if row["id"] in register:
                raise ProvenanceError(f"{register_csv}: duplicate id {row['id']!r}")
            register[row["id"]] = (row["shipped_weights_training"] or "").strip()
    return register


def _tables(doc: dict, key: str) -> tuple[list[dict], str | None]:
    """`doc[key]` as a list of tables, or an error message if it has the wrong shape."""
    value = doc.get(key, [])
    if not isinstance(value, list) or not all(isinstance(t, dict) for t in value):
        return [], f"`{key}` must be an array of tables ([[{key}]])"
    return value, None


def _is_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _artifact_entries(doc: dict) -> list[str] | None:
    """The artifact paths the manifest names (`artifact`, or each of `artifacts`), or None if it
    names none in a usable form (`_check_format` says why)."""
    if "artifact" in doc and "artifacts" not in doc:
        return [doc["artifact"]] if _is_text(doc["artifact"]) else None
    many = doc.get("artifacts")
    if "artifact" not in doc and isinstance(many, list) and many and all(_is_text(a) for a in many):
        return many
    return None


def _check_format(manifest: Path, doc: dict) -> list[str]:
    """Top-level shape: only artifact(s)/note/source/signoff, exactly one of `artifact` and
    `artifacts`, and a note."""
    violations: list[str] = []
    for key in doc:
        if key in _TOP_LEVEL_KEYS:
            continue
        hint = difflib.get_close_matches(key.lower(), _TOP_LEVEL_KEYS, n=1)
        suffix = f" (did you mean {hint[0]!r}?)" if hint else ""
        violations.append(
            f"{manifest}: unknown top-level key {key!r}{suffix}; "
            f"allowed keys are {', '.join(_TOP_LEVEL_KEYS)}"
        )
    if "artifact" in doc and "artifacts" in doc:
        violations.append(f"{manifest}: give `artifact` or `artifacts`, not both")
    elif "artifact" not in doc and "artifacts" not in doc:
        violations.append(f"{manifest}: missing required key `artifact` (or `artifacts`)")
    elif "artifact" in doc and not _is_text(doc["artifact"]):
        violations.append(f"{manifest}: `artifact` must be a non-empty string")
    elif "artifacts" in doc and _artifact_entries(doc) is None:
        violations.append(f"{manifest}: `artifacts` must be a non-empty array of non-empty strings")
    if "note" not in doc:
        violations.append(f"{manifest}: missing required key `note`")
    elif not _is_text(doc["note"]):
        violations.append(f"{manifest}: `note` must be a non-empty string")
    return violations


def _check_one(register: dict[str, str], manifest: Path) -> list[str]:
    try:
        with manifest.open("rb") as f:
            doc = tomllib.load(f)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        return [f"{manifest}: cannot read manifest: {e}"]

    violations = _check_format(manifest, doc)
    sources, err = _tables(doc, "source")
    if err:
        violations.append(f"{manifest}: {err}")
    signoffs, err = _tables(doc, "signoff")
    if err:
        violations.append(f"{manifest}: {err}")

    signed: set[str] = set()
    for s in signoffs:
        sid = s.get("id")
        has_id = isinstance(sid, str) and bool(sid)
        if not has_id:
            violations.append(f"{manifest}: [[signoff]] without a string `id`")
        if not _is_text(s.get("by")):
            who = repr(sid) if has_id else "(no id)"
            violations.append(f"{manifest}: [[signoff]] for {who} needs a non-empty string `by`")
        elif has_id:
            signed.add(sid)

    for s in sources:
        sid = s.get("id")
        if not isinstance(sid, str) or not sid:
            violations.append(f"{manifest}: [[source]] without a string `id`")
            continue
        if sid not in register:
            violations.append(f"{manifest}: source {sid!r} is unknown (not in the data register)")
            continue
        value = register[sid]
        if value == "allow":
            continue
        if value == "deny":
            violations.append(f"{manifest}: source {sid!r} is deny (not allowed in shipped weights or calibration)")
        elif value == "verify":
            if sid not in signed:
                violations.append(f"{manifest}: source {sid!r} is verify and has no matching [[signoff]]")
        elif value == "n/a":
            violations.append(f"{manifest}: source {sid!r} is n/a (not a dataset or weights source)")
        else:
            violations.append(
                f"{manifest}: source {sid!r} has unrecognised shipped_weights_training {value!r} "
                f"(expected one of {', '.join(sorted(_VALUES))})"
            )
    return violations


def check(register_csv: str | Path, manifests: Iterable[Path]) -> list[str]:
    """Return one human-readable violation per problem found in `manifests` (empty list = clean).

    A file that appears more than once is checked once.
    """
    register = load_register(Path(register_csv))
    violations: list[str] = []
    seen: set[Path] = set()
    for m in manifests:
        m = Path(m)
        key = m.resolve()
        if key in seen:
            continue
        seen.add(key)
        violations.extend(_check_one(register, m))
    return violations


def _artifact_problem(artifact: str, repo_root: Path, pack_dir: Path) -> str | None:
    """Why `artifact` is not a regular file inside `pack_dir`, or None if it is.

    The path is relative to the repo root (so `packs/cmn/cmn.calib.json`), and what it names must
    lie inside the pack's own directory once `..` parts and symlinks are resolved.
    """
    if Path(artifact).is_absolute():
        return "must be a relative path, not an absolute one"
    try:
        target = (repo_root / artifact).resolve()
        if not target.is_relative_to(pack_dir):
            return f"is outside the pack directory {pack_dir} (no `..` escapes or links out of it)"
        if not target.exists():
            return f"does not exist (resolved against {repo_root})"
        if not target.is_file():
            return "is not a regular file"
    except (OSError, ValueError, RuntimeError) as e:  # an embedded NUL; a symlink loop (RuntimeError on 3.11/3.12)
        return f"is not a usable path: {e}"
    return None


def _uncovered_data_files(pack_dir: Path, repo_root: Path, artifacts: list[str]) -> list[Path]:
    """The data files (`_DATA_SUFFIXES`, at any depth) in `pack_dir`, other than the manifest, that
    no artifact names. Paths are compared as written (relative to the repo root, `..` folded),
    not through symlinks: an artifact that strays outside the pack is reported on its own."""
    named = {os.path.normpath(repo_root / a) for a in artifacts}
    files = sorted(
        f
        for f in pack_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in _DATA_SUFFIXES and f.name != _MANIFEST_NAME
    )
    return [f for f in files if os.path.normpath(f) not in named]


def _artifact_violations(manifest: Path, repo_root: Path) -> list[str]:
    """Each of the manifest's artifacts (repo-root-relative paths) must be a regular file inside the
    manifest's own directory, and every data file in that directory must be one of them."""
    try:
        with manifest.open("rb") as f:
            artifacts = _artifact_entries(tomllib.load(f))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []  # check() reports an unreadable manifest
    if artifacts is None:
        return []  # check() reports a missing, empty or malformed artifact
    pack_dir = manifest.parent.resolve()
    violations = []
    for artifact in artifacts:
        problem = _artifact_problem(artifact, repo_root, pack_dir)
        if problem:
            violations.append(f"{manifest}: artifact {artifact!r} {problem}")
    for data_file in _uncovered_data_files(pack_dir, repo_root, artifacts):
        try:
            shown = data_file.relative_to(repo_root).as_posix()
        except ValueError:  # a pack directory that is a link to somewhere outside the repo
            shown = data_file.as_posix()
        violations.append(
            f"{manifest}: data file {shown!r} is not covered: list it under `artifacts` "
            f"(or drop it from the pack)"
        )
    return violations


def check_packs(register_csv: str | Path, packs_root: str | Path, manifests: Iterable[Path] = ()) -> list[str]:
    """Check every pack under `packs_root`, plus any extra `manifests`.

    Each immediate subdirectory of `packs_root` must hold a PROVENANCE.toml whose `artifact` (or
    each of its `artifacts`) is a regular file inside that subdirectory, and that names every
    `*.toml` and `*.json` file in it. Artifact paths are relative to the repo root, which is the
    parent of `packs_root` (e.g. `packs/cmn/cmn.calib.json`). Every manifest found is then checked
    like an explicit one.
    """
    packs_root = Path(packs_root)
    violations: list[str] = []
    found: list[Path] = []
    if not packs_root.is_dir():
        violations.append(f"{packs_root}: packs root is not a directory")
    else:
        repo_root = packs_root.resolve().parent
        packs = sorted(p for p in packs_root.iterdir() if p.is_dir())
        if not packs:
            violations.append(f"{packs_root}: no pack directories found")
        for pack in packs:
            manifest = pack / _MANIFEST_NAME
            if not manifest.is_file():
                violations.append(f"{pack}: pack has no {_MANIFEST_NAME}")
                continue
            found.append(manifest)
            violations.extend(_artifact_violations(manifest, repo_root))
    violations.extend(check(register_csv, [*found, *manifests]))
    return violations


def _run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not args.files and args.packs_root is None:
        parser.error("give at least one PROVENANCE.toml file or --packs-root")
    if args.packs_root is not None and not args.packs_root.strip():
        # Path("") is the current directory: an empty value (an unset shell variable, say) must
        # neither be skipped nor silently mean "here".
        parser.error("--packs-root must not be empty")
    files = [Path(f) for f in args.files]
    try:
        if args.packs_root is not None:
            violations = check_packs(args.register, args.packs_root, files)
        else:
            violations = check(args.register, files)
    except (OSError, ProvenanceError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if violations:
        for v in violations:
            print(v)
        return 1
    print("provenance ok")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("provenance", help="check PROVENANCE.toml files against data-register.csv")
    p.add_argument("--register", required=True, help="path to data-register.csv")
    p.add_argument(
        "--packs-root",
        metavar="DIR",
        help="also require every subdirectory of DIR to have a PROVENANCE.toml that names each of "
        "its data files (*.toml, *.json) as an existing artifact (paths relative to DIR/..), "
        "and check those files",
    )
    p.add_argument("files", nargs="*", help="PROVENANCE.toml files to check")
    p.set_defaults(func=lambda args: _run(args, p))
