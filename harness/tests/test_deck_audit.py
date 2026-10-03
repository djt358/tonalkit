"""deck_build.audit: the sheet DJ reads on GitHub."""

from deck_support import needs_c0_fix, small_deck_data

from tonekit_harness.deck_build.audit import COLUMNS, audit_markdown
from tonekit_harness.deck_build.fingerprint import card_fingerprint

pytestmark = needs_c0_fix


def sheet_rows(sheet: str) -> dict[str, list[str]]:
    table = [line for line in sheet.splitlines() if line.startswith("| ")]
    return {line.split(" | ")[0].removeprefix("| "): [c.strip() for c in line.strip("|").split(" | ")] for line in table[1:]}


def test_the_sheet_says_how_to_reply_and_then_has_one_table():
    sheet = audit_markdown(small_deck_data(), {}, "the stand-in gate_standin.csv")
    lines = sheet.splitlines()
    assert lines[0] == "# Prompt deck t-v1: audit sheet"
    assert "5 cards (register 1, gate 4)" in lines[2] and "Gate phrases: the stand-in gate_standin.csv." in lines[2]
    assert "0 of 5 approved" in lines[2]
    assert lines[4].startswith('**How to reply.** "approve all"') and "reject" in lines[4] and "fix" in lines[4]
    assert "fingerprint" in lines[4]
    assert COLUMNS == [
        "id", "set", "text", "traditional", "pinyin shown", "context", "label", "note", "fingerprint", "status", "flag",
    ]  # fmt: skip
    assert lines[8] == "| " + " | ".join(COLUMNS) + " |"
    assert len([x for x in lines if x.startswith("| ")]) == 6  # the header and one row per card


def test_a_row_shows_what_the_volunteer_sees_the_note_in_both_scripts_the_fingerprint_and_the_flag():
    data = small_deck_data()
    rows = sheet_rows(audit_markdown(data, {"g01-c": "stand-in phrase", "g01-e": "look here"}))
    assert len(rows) == 5
    c, e = rows["g01-c"], rows["g01-e"]
    assert c[:7] == ["g01-c", "gate", "一杯水", "一杯水", "yì bēi shuǐ", "phrase", "correct"]
    assert (c[9], c[10]) == ("unverified", "stand-in phrase")
    assert e[6] == "tone_error (syllable 3)" and e[2:5] == ["一杯睡", "一杯睡", "yì bēi shuì"]
    assert e[7] == (
        "Read it as written: 睡 as in 睡觉 (to sleep).<br>traditional: Read it as written: 睡 as in 睡覺 (to sleep)."
    )
    card = next(x for x in data["card"] if x["id"] == "g01-e")
    assert e[8] == f"`{card_fingerprint(card)}`" and e[10] == "look here"
    assert rows["r01"][3] == "媽麻馬罵"


def test_a_note_that_is_the_same_in_both_scripts_is_shown_once_and_a_bar_does_not_break_the_table():
    data = small_deck_data(1)
    data["card"][0]["prompt_note"] = "a | b"
    data["card"][0]["prompt_note_traditional"] = "a | b"
    rows = sheet_rows(audit_markdown(data, {}))
    assert rows["r01"][7] == "a \\| b"


def test_the_sheet_counts_approved_cards():
    data = small_deck_data()
    data["card"][0]["status"] = "approved"
    assert "1 of 5 approved" in audit_markdown(data, {}).splitlines()[2]
