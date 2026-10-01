"""What every contract model shares: strict parsing, and readable validation errors."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError


class StrictModel(BaseModel):
    # Unknown keys are errors: a typo such as "distractor" must not silently drop data.
    model_config = ConfigDict(extra="forbid")


def format_validation_error(e: ValidationError) -> str:
    """One line per problem, `<field path>: <message>` (just the message for a model-level
    check, which already names the card or field it is about)."""
    lines = []
    for err in e.errors():
        where = ".".join(str(part) for part in err["loc"])
        msg = err["msg"].removeprefix("Value error, ")
        lines.append(f"{where}: {msg}" if where else msg)
    return "\n".join(lines)
