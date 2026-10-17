"""The accent a speaker is graded against."""

from __future__ import annotations

from ..contracts.registry import Speaker, speaker_accent


def accent_for(speaker: Speaker, lect: str = "cmn", *, override: str | None = None) -> str:
    """`override` (evaluate's `--accent`) if there is one, else `contracts.registry.speaker_accent`:
    the speaker's own `accent`, else the default for where they grew up hearing the lect (R82)."""
    return override or speaker_accent(speaker, lect)
