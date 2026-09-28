"""Data-provenance check: every PROVENANCE.toml source must be cleared by data-register.csv."""

from __future__ import annotations

import argparse
import csv
import sys
import tomllib
from pathlib import Path

_VALUES = {"allow", "verify", "deny", "n/a"}


class ProvenanceError(ValueError):
    """The register itself is unusable (as opposed to a manifest violating it)."""


def _load_register(register_csv: Path) -> dict[str, str]:
    with Path(register_csv).open(newline="", encoding="utf-8") as f:
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


def _check_one(register: dict[str, str], manifest: Path) -> list[str]:
    try:
        with manifest.open("rb") as f:
            doc = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        return [f"{manifest}: cannot read manifest: {e}"]

    violations: list[str] = []
    sources, err = _tables(doc, "source")
    if err:
        violations.append(f"{manifest}: {err}")
    signoffs, err = _tables(doc, "signoff")
    if err:
        violations.append(f"{manifest}: {err}")

    signed: set[str] = set()
    for s in signoffs:
        sid = s.get("id")
        if isinstance(sid, str) and sid:
            signed.add(sid)
        else:
            violations.append(f"{manifest}: [[signoff]] without a string `id`")

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


def check(register_csv: str | Path, manifests: list[Path]) -> list[str]:
    """Return one human-readable violation per problem found in `manifests` (empty list = clean)."""
    register = _load_register(Path(register_csv))
    violations: list[str] = []
    for m in manifests:
        violations.extend(_check_one(register, Path(m)))
    return violations


def _run(args: argparse.Namespace) -> int:
    try:
        violations = check(args.register, [Path(f) for f in args.files])
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
    p.add_argument("files", nargs="+", help="PROVENANCE.toml files to check")
    p.set_defaults(func=_run)
