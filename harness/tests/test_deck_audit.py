"""deck_build.audit: the sheet DJ reads."""

from deck_support import small_deck_data

from tonekit_harness.deck_build.audit import audit_markdown


def test_the_sheet_has_a_row_per_card_with_tones_note_and_flag():
    data = small_deck_data()
    sheet = audit_markdown(data, {"g01-c": "look here"}, "the stand-in")
    lines = sheet.splitlines()
    assert lines[0] == "Gate phrases: the stand-in." and lines[2].startswith("| id | set | text |")
    rows = {line.split(" | ")[0].removeprefix("| "): line for line in lines[4:]}
    assert len(rows) == 5
    assert "| 4-1-3 | 4-1-3 | look here |" in rows["g01-c"]
    assert "| tone_error | 4-1-3 | 4-1-4 (syllable 3 is the error) |" in rows["g01-e"]
    assert 'note: "Read it as written: 睡 as in 睡觉 (to sleep)."' in rows["g01-e"]
    assert "媽麻馬罵" in rows["r01"]


def test_without_a_source_there_is_no_heading():
    assert audit_markdown(small_deck_data(), {}).startswith("| id | set |")
