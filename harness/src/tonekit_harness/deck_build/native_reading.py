"""How many ways native speakers say a phrase (R89). A card grades one list of produced tones, so a
phrase that has two native readings (a run of three third tones, 一把雨伞) would mark the other
reading wrong; the contract refuses such a `correct` card, and the gate leaves the row out and says why."""

from __future__ import annotations

from .reading import RULES, Reading


def native_readings(reading: Reading) -> list[tuple[str, ...]]:
    """The surface tone sequences the contract accepts for the reading's citation pinyin, sorted."""
    syllables = reading.citation()
    return sorted(
        RULES.surface_options([s.tone for s in syllables], [s.base for s in syllables], reading.context, reading.text)
    )


def native_reading_problem(reading: Reading, what: str = "a gate phrase") -> str | None:
    """Why the reading cannot be a scored phrase, if it has more than one native reading."""
    found = native_readings(reading)
    if len(found) < 2:
        return None
    shown = ", ".join("-".join(tones) for tones in found)
    return f"has {len(found)} native readings ({shown}); {what} needs one (R89)"
