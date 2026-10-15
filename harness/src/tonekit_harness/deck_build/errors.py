"""The one error the builder raises: a source that cannot become part of the deck."""

from __future__ import annotations


class BuildError(ValueError):
    """A source file is unreadable or a card cannot be made; the message names the file and line."""
