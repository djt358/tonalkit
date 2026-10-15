"""A tonekit `Register` as the one JSON text the harness passes to `analyze` (and keys the
analysis cache on): sorted keys, no spaces, so equal registers are equal text."""

from __future__ import annotations

import json


def register_json(register: dict) -> str:
    return json.dumps(register, sort_keys=True, separators=(",", ":"))
