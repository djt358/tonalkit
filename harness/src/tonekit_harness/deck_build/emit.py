"""Writing the deck: the contract file (TOML) and the same cards as JSON for the kit. Both are
deterministic, so a rebuild from unchanged sources changes no byte (the kit hashes the JSON it
loads, and a session records that hash)."""

from __future__ import annotations

import json
from pathlib import Path

from .contract_view import contract_card


def _string(value: str) -> str:
    # A JSON string is a valid TOML basic string (same escapes); keep hanzi as they are.
    return json.dumps(value, ensure_ascii=False)


def _value(value: object) -> str:
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_value(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"cannot write {value!r} as TOML")


def toml_text(data: dict) -> str:
    """The deck contract file: `[deck]`, then one `[[card]]` per card in key order. Fields the
    contract model cannot hold yet (see `contract_view`) are left out."""
    lines = ["[deck]"] + [f"{k} = {_value(v)}" for k, v in data["deck"].items()]
    for card in data["card"]:
        lines += ["", "[[card]]"] + [f"{k} = {_value(v)}" for k, v in contract_card(card).items()]
    return "\n".join(lines) + "\n"


def json_text(data: dict) -> str:
    """The kit's deck: `{"deck": {...}, "card": [...]}`, every field the cards carry."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def write_deck(data: dict, out_dir: str | Path) -> list[Path]:
    """Write `<id>.toml` and `<id>.json` into `out_dir` (created); returns the two paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    deck_id = data["deck"]["id"]
    written = []
    for suffix, text in (("toml", toml_text(data)), ("json", json_text(data))):
        path = out / f"{deck_id}.{suffix}"
        path.write_bytes(text.encode("utf-8"))
        written.append(path)
    return written
