"""`tkh schema`: write the JSON Schema of each S0.5 format (docs/s05/contracts.md), which the kit's
JavaScript tests validate against. The output is deterministic, so the committed copy under
kit/schema/ can be checked against a fresh run."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from .contracts.bundle import Session
from .contracts.deck import Deck
from .contracts.gate import GateFile
from .contracts.registry import CorpusFile
from .repo import repo_root

# file name -> the model that owns the format
FORMATS: dict[str, type[BaseModel]] = {
    "session.schema.json": Session,
    "deck.schema.json": Deck,
    "corpus.schema.json": CorpusFile,
    "gate.schema.json": GateFile,
}


def default_out_dir() -> Path:
    return repo_root() / "kit" / "schema"


def schema_text(model: type[BaseModel]) -> str:
    return json.dumps(model.model_json_schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_schemas(out: Path) -> list[Path]:
    """Write every format's schema into `out` (created) and return the paths, in name order."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name in sorted(FORMATS):
        path = out / name
        path.write_text(schema_text(FORMATS[name]), encoding="utf-8")
        written.append(path)
    return written


def _run(args: argparse.Namespace) -> int:
    out = Path(args.out) if args.out else default_out_dir()
    for path in write_schemas(out):
        print(f"wrote {path}")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("schema", help="write the JSON Schemas of the S0.5 formats (default: kit/schema)")
    p.add_argument("--out", metavar="DIR", help="output directory (default: kit/schema in the repository)")
    p.set_defaults(func=_run)
