"""What the contracts need to know of a language pack: its lect, tone ids and accent ids. They come
from the pack TOML (`[[tone]] id`, `[[accent]] id`), never from a list in code."""

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
    accent_ids: frozenset[str]


def default_pack_path() -> Path:
    return repo_root() / "packs" / "cmn" / "cmn.toml"


def load_pack_info(pack: str | Path | None) -> PackInfo:
    """The lect, tone ids and accent ids of the pack TOML at `pack` (default: packs/cmn/cmn.toml)."""
    path = Path(pack) if pack is not None else default_pack_path()
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise PackError(f"{path}: invalid TOML: {e}") from e
    lect = doc.get("pack", {}).get("lect")
    if not isinstance(lect, str) or not lect:
        raise PackError(f"{path}: the pack has no [pack] lect")
    tones = _ids(doc, "tone", path)
    if not tones:
        raise PackError(f"{path}: the pack has no [[tone]] entries")
    return PackInfo(lect=lect, tone_ids=frozenset(tones), accent_ids=frozenset(_ids(doc, "accent", path)))


def _ids(doc: dict, table: str, path: Path) -> list[str]:
    """The `id` of each `[[table]]` entry; a missing or repeated id is an error."""
    ids: list[str] = []
    for entry in doc.get(table, []):
        if "id" not in entry:
            raise PackError(f"{path}: a [[{table}]] without an id")
        if entry["id"] in ids:
            raise PackError(f"{path}: duplicate {table} id {entry['id']!r}")
        ids.append(entry["id"])
    return ids
