"""What the contracts need to know of a language pack: its lect and tone ids. The tone inventory
comes from the pack TOML (`[[tone]] id`), never from a list in code."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..repo import repo_root


class PackError(ValueError):
    """The pack TOML could not be read as a pack; the message starts with its path."""


@dataclass(frozen=True)
class PackInfo:
    lect: str
    tone_ids: frozenset[str]


def default_pack_path() -> Path:
    return repo_root() / "packs" / "cmn" / "cmn.toml"


def load_pack_info(pack: str | Path | None) -> PackInfo:
    """The lect and tone ids of the pack TOML at `pack` (default: packs/cmn/cmn.toml)."""
    path = Path(pack) if pack is not None else default_pack_path()
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise PackError(f"{path}: invalid TOML: {e}") from e
    lect = doc.get("pack", {}).get("lect")
    if not isinstance(lect, str) or not lect:
        raise PackError(f"{path}: the pack has no [pack] lect")
    ids: list[str] = []
    for tone in doc.get("tone", []):
        if "id" not in tone:
            raise PackError(f"{path}: a [[tone]] without an id")
        if tone["id"] in ids:
            raise PackError(f"{path}: duplicate tone id {tone['id']!r}")
        ids.append(tone["id"])
    if not ids:
        raise PackError(f"{path}: the pack has no [[tone]] entries")
    return PackInfo(lect=lect, tone_ids=frozenset(ids))
