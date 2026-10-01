"""The two cards of a pair: a correct reading and its deliberate single-tone error."""

from __future__ import annotations

from .cards import candidate, make_card
from .reading import Reading


def pair_cards(
    set_: str, pair: str, correct: Reading, error: Reading, *, note: str, status: str = "unverified"
) -> tuple[dict, dict]:
    """`<pair>-c` (correct) and `<pair>-e` (tone_error). Both intend the correct reading's surface
    tones, so a pair shares `intended`; the error card asks for the error's own surface tones."""
    c = make_card(
        id=f"{pair}-c", set=set_, pair=pair, label="correct", reading=correct,
        intended=candidate(pair, correct.spoken_pinyin), status=status,
    )  # fmt: skip
    e = make_card(
        id=f"{pair}-e", set=set_, pair=pair, label="tone_error", reading=error,
        intended=candidate(pair, correct.spoken_pinyin), note=note, status=status,
    )  # fmt: skip
    return c, e
