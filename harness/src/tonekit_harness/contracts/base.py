"""What every contract model shares: strict parsing, and readable validation errors."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, ValidationError


class StrictModel(BaseModel):
    # Unknown keys are errors: a typo such as "distractor" must not silently drop data.
    model_config = ConfigDict(extra="forbid")


def format_validation_error(
    e: ValidationError, data: object = None, names: Mapping[str, str] | None = None
) -> str:
    """One line per problem. A field error reads `<path>: <message>`; a check on a whole list item
    (whose message names the item itself) is just the message. With the raw `data` and `names`
    (list field -> the key that names its items, e.g. {"card": "id"}), `card.3.set` reads
    `card 'g01-e'.set`."""
    lines = []
    for err in e.errors():
        loc = err["loc"]
        msg = err["msg"].removeprefix("Value error, ")
        if not loc or isinstance(loc[-1], int):
            lines.append(msg)
        else:
            lines.append(f"{_path(loc, data, names or {})}: {msg}")
    return "\n".join(lines)


def _path(loc: tuple[int | str, ...], data: object, names: Mapping[str, str]) -> str:
    parts: list[str] = []
    node = data
    for key in loc:
        node = _step(node, key)
        if isinstance(key, int) and parts and parts[-1] in names:
            label = node.get(names[parts[-1]]) if isinstance(node, dict) else None
            parts[-1] = f"{parts[-1]} {label!r}" if label is not None else f"{parts[-1]}.{key}"
        else:
            parts.append(str(key))
    return ".".join(parts)


def _step(node: object, key: int | str) -> object:
    try:
        return node[key]  # type: ignore[index]
    except (KeyError, IndexError, TypeError):
        return None
