"""Where the volunteer kit's text lives, and how the kit tests read it. The text is the product here:
what volunteers are told and promised, so the tests read the files as they ship."""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "kit"
GUIDE = KIT / "GUIDE.md"
CONSENT = KIT / "CONSENT.md"
PROMISES = KIT / "PROMISES.md"
COPY = KIT / "copy.json"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def copy() -> dict[str, str]:
    return json.loads(text(COPY))


def volunteer_text() -> str:
    """Everything a volunteer reads: the guide, the consent and every string the kit shows."""
    return "\n".join([text(GUIDE), text(CONSENT), *copy().values()])
