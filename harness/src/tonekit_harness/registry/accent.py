"""The accent a speaker is graded against."""

from __future__ import annotations

from ..contracts.registry import Speaker, default_accent


def accent_for(speaker: Speaker, lect: str = "cmn", *, override: str | None = None) -> str:
    """`override` (evaluate's `--accent`) if there is one, else the speaker's own `accent`, else the
    default for where they grew up hearing the lect (`default_accent`: `taiwan` is cmn-TW,
    everything else cmn-standard)."""
    if override:
        return override
    if speaker.accent:
        return speaker.accent
    return default_accent(speaker.grew_up_hearing or "prefer_not", lect)
