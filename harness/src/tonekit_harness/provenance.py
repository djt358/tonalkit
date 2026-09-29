"""Data-provenance check: every PROVENANCE.toml source must be cleared by data-register.csv."""

from __future__ import annotations

import argparse
import csv
import difflib
import sys
import tomllib
from collections.abc import Iterable
from pathlib import Path

_VALUES = {"allow", "verify", "deny", "n/a"}
_TOP_LEVEL_KEYS = ("artifact", "note", "source", "signoff")
_MANIFEST_NAME = "PROVENANCE.toml"


class ProvenanceError(ValueError):
    """The register itself is unusable (as opposed to a manifest violating it)."""


def _load_register(register_csv: Path) -> dict[str, str]:
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


def _check_format(manifest: Path, doc: dict) -> list[str]:
    """Top-level shape: only artifact/note/source/signoff, and artifact and note present."""
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
    for key in ("artifact", "note"):
        if key not in doc:
            violations.append(f"{manifest}: missing required key `{key}`")
        elif not _is_text(doc[key]):
            violations.append(f"{manifest}: `{key}` must be a non-empty string")
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
    register = _load_register(Path(register_csv))
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
    except (OSError, ValueError) as e:  # e.g. an embedded NUL character
        return f"is not a usable path: {e}"
    return None


def _artifact_violations(manifest: Path, repo_root: Path) -> list[str]:
    """The manifest's `artifact` (a repo-root-relative path) must be a regular file inside the
    manifest's own directory."""
    try:
        with manifest.open("rb") as f:
            artifact = tomllib.load(f).get("artifact")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []  # check() reports an unreadable manifest
    if not _is_text(artifact):
        return []  # check() reports a missing or empty artifact
    problem = _artifact_problem(artifact, repo_root, manifest.parent.resolve())
    return [f"{manifest}: artifact {artifact!r} {problem}"] if problem else []


def check_packs(register_csv: str | Path, packs_root: str | Path, manifests: Iterable[Path] = ()) -> list[str]:
    """Check every pack under `packs_root`, plus any extra `manifests`.

    Each immediate subdirectory of `packs_root` must hold a PROVENANCE.toml whose `artifact` is a
    regular file inside that subdirectory. Artifact paths are relative to the repo root, which is
    the parent of `packs_root` (e.g. `packs/cmn/cmn.calib.json`). Every manifest found is then
    checked like an explicit one.
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
        help="also require every subdirectory of DIR to have a PROVENANCE.toml whose artifact exists "
        "(artifact paths are relative to DIR/..), and check those files",
    )
    p.add_argument("files", nargs="*", help="PROVENANCE.toml files to check")
    p.set_defaults(func=lambda args: _run(args, p))
