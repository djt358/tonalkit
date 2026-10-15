"""TOML values as text, for the files the harness writes (the deck contract file, corpus.toml).
The standard library reads TOML but does not write it; these files only hold strings, integers,
lists and inline tables."""

from __future__ import annotations

import json


def toml_string(value: str) -> str:
    # A JSON string is a valid TOML basic string (same escapes); keep hanzi as they are.
    return json.dumps(value, ensure_ascii=False)


def toml_value(value: object) -> str:
    """`value` as a TOML value: a string, an integer (not a bool), a list or an inline table."""
    if isinstance(value, str):
        return toml_string(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {toml_value(v)}" for k, v in value.items()) + " }"
    raise TypeError(f"cannot write {value!r} as TOML")
