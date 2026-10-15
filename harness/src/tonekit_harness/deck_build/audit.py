"""The audit sheet DJ reads on GitHub before approving the deck (`kit/deck/<id>.audit.md`): one
table, a row per card, with what the volunteer sees, how it is to be read, the card's fingerprint
(what an approval is pinned to, R91), its status and what to look at. The builder writes it."""

from __future__ import annotations

from collections import Counter

from .fingerprint import card_fingerprint

COLUMNS = [
    "id", "set", "text", "traditional", "pinyin shown", "context", "label", "note", "fingerprint", "status", "flag",
]  # fmt: skip


def _label(card: dict) -> str:
    if card["label"] != "tone_error":
        return card["label"]
    changed = [
        i + 1 for i, (p, t) in enumerate(zip(card["produced_tones"], card["intended"]["tones"], strict=True)) if p != t
    ]
    return f"tone_error (syllable {changed[0]})"


def _note(card: dict) -> str:
    """The note, and under it the traditional version when that differs."""
    note, traditional = card["prompt_note"], card.get("prompt_note_traditional", "")
    if traditional and traditional != note:
        return f"{note}<br>traditional: {traditional}"
    return note


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _header(data: dict, gate_source: str) -> list[str]:
    cards = data["card"]
    sets = ", ".join(f"{k} {n}" for k, n in Counter(c["set"] for c in cards).items())
    approved = sum(c["status"] == "approved" for c in cards)
    source = f" Gate phrases: {gate_source}." if gate_source else ""
    return [
        f"# Prompt deck {data['deck']['id']}: audit sheet",
        "",
        f"Every card as a volunteer sees it: {len(cards)} cards ({sets}).{source} {approved} of {len(cards)} approved.",
        "",
        '**How to reply.** "approve all" approves every card as it is shown here. Otherwise list the ids '
        'to reject or fix ("reject g09-e", "fix r01: ...") and the rest are approved. An approval is '
        "pinned to the fingerprint column, so a card that changes later needs approving again.",
        "",
        "Written by `tkh deck build`; do not edit by hand.",
        "",
    ]


def audit_markdown(data: dict, flags: dict[str, str], gate_source: str = "") -> str:
    """The sheet for a deck (a dict of `{"deck", "card"}`; `flags` maps a card id to what DJ should
    look at), under a short note on how to reply."""
    lines = _header(data, gate_source)
    lines += ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for card in data["card"]:
        cells = [
            card["id"], card["set"], card["text"], card.get("text_traditional", ""), card["pinyin"],
            card["context"], _label(card), _note(card), f"`{card_fingerprint(card)}`", card["status"],
            flags.get(card["id"], ""),
        ]  # fmt: skip
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"
