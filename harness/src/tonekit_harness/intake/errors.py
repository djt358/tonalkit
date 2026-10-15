"""The error intake and purge raise for a bundle or data root they refuse; the message says why
and, where there is one, what to do."""

from __future__ import annotations


class IntakeError(ValueError):
    """Intake or purge refused; nothing was written."""
