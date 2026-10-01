"""The audit sheet DJ reads before approving the deck: one row per card with what it shows, how it
is to be read, and what to look at."""

from __future__ import annotations


def _tones(tones: list[str]) -> str:
    return "-".join(tones)


def _produced(card: dict) -> str:
    produced = _tones(card["produced_tones"])
    if card["label"] != "tone_error":
        return produced
    changed = [
        i + 1 for i, (p, t) in enumerate(zip(card["produced_tones"], card["intended"]["tones"], strict=True)) if p != t
    ]
    return f"{produced} (syllable {changed[0]} is the error)"


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def audit_markdown(data: dict, flags: dict[str, str]) -> str:
    """A markdown table of every card of the deck (a dict of `{"deck", "card"}`)."""
    head = "| id | set | text | traditional | pinyin | context | label | intended | produced | flags and note |"
    lines = [head, "|" + "---|" * 10]
    for card in data["card"]:
        extras = [flags[card["id"]]] if card["id"] in flags else []
        if card["prompt_note"]:
            extras.append(f'note: "{card["prompt_note"]}"')
        cells = [
            card["id"], card["set"], card["text"], card.get("text_traditional", ""), card["pinyin"],
            card["context"], card["label"], _tones(card["intended"]["tones"]), _produced(card), " / ".join(extras),
        ]  # fmt: skip
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"
