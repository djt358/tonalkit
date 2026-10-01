"""Error text shared by the registry modules."""

from __future__ import annotations


def reason(e: Exception) -> str:
    """Why a file could not be read: the system's words for an `OSError` ("Permission denied"),
    else the error's own text (a `UnicodeDecodeError`)."""
    return getattr(e, "strerror", None) or str(e)


class SelectionError(ValueError):
    """A selection was asked for in a way that cannot mean anything: a corpus id that is not
    there, an unknown split, an empty list."""
