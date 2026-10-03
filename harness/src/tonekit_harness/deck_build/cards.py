"""Card dicts in the contract's key order (docs/s05/contracts.md section 1). Each is plain data:
the contract models check it when the deck is assembled."""

from __future__ import annotations

from collections.abc import Sequence

from .reading import RULES, Reading


def candidate(candidate_id: str, pinyin: str) -> dict:
    """An `intended` or distractor candidate: the surface tones of `pinyin` and its toneless
    syllables as labels."""
    syllables = RULES.parse_pinyin(pinyin)
    return {
        "id": candidate_id,
        "tones": [s.tone for s in syllables],
        "labels": [s.base for s in syllables],
    }


def make_card(
    *,
    id: str,
    set: str,
    label: str,
    reading: Reading,
    intended: dict,
    pair: str | None = None,
    distractors: Sequence[dict] = (),
    note: str = "",
    note_traditional: str = "",
) -> dict:
    """The card for `reading`: it asks for the tones of `reading.spoken_pinyin`. Every card is
    `unverified`: DJ's approval is applied afterwards, pinned to the card's fingerprint (R91)."""
    card: dict = {"id": id, "set": set}
    if pair is not None:
        card["pair"] = pair
    card |= {"label": label, "text": reading.text}
    if reading.text_traditional is not None:
        card["text_traditional"] = reading.text_traditional
    card |= {
        "pinyin": reading.spoken_pinyin,
        "citation_pinyin": reading.citation_pinyin,
        "context": reading.context,
        "intended": intended,
        "produced_tones": [s.tone for s in reading.spoken()],
        "distractors": list(distractors),
        "prompt_note": note,
    }
    if note_traditional:
        card["prompt_note_traditional"] = note_traditional
    card["status"] = "unverified"
    return card
