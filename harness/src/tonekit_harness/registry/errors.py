"""Error text shared by the registry modules."""

from __future__ import annotations

MAX_PROBLEMS_SHOWN = 10


def reason(e: Exception) -> str:
    """Why a file could not be read: the system's words for an `OSError` ("Permission denied"),
    else the error's own text (a `UnicodeDecodeError`)."""
    return getattr(e, "strerror", None) or str(e)


def cut(problems: list[str], more: str = "and {} more") -> list[str]:
    """The first `MAX_PROBLEMS_SHOWN` problems, then `more` (formatted with how many are left out)
    when there are others: an error lists every kind of problem without burying the first."""
    if len(problems) <= MAX_PROBLEMS_SHOWN:
        return list(problems)
    return problems[:MAX_PROBLEMS_SHOWN] + [more.format(len(problems) - MAX_PROBLEMS_SHOWN)]


class SelectionError(ValueError):
    """A selection was asked for in a way that cannot mean anything: a corpus id that is not
    there, an unknown split, an empty list, a selector that selects nothing."""
