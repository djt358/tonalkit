"""R91: a card's fingerprint, the approvals file and applying approvals to cards."""

import pytest

from tonekit_harness.deck_build.approval_apply import apply_approvals
from tonekit_harness.deck_build.approvals import Approval, approvals_text, merge, read_approvals, write_approvals
from tonekit_harness.deck_build.cards import candidate, make_card
from tonekit_harness.deck_build.errors import BuildError
from tonekit_harness.deck_build.fingerprint import canonical_json, card_fingerprint
from tonekit_harness.deck_build.reading import Reading


def card(card_id="r01", text="水", pinyin="shuǐ", note="", note_traditional="", trad="水"):
    return make_card(
        id=card_id, set="register", label="correct", reading=Reading(text, pinyin, pinyin, "isolated", trad),
        intended=candidate(card_id, pinyin), note=note, note_traditional=note_traditional,
    )  # fmt: skip


def test_the_canonical_json_is_sorted_compact_unescaped_and_has_no_status():
    assert canonical_json({"text": "水", "status": "approved", "id": "a", "tones": ["3"], "in": {"b": 1, "a": "x"}}) == (
        '{"id":"a","in":{"a":"x","b":1},"text":"水","tones":["3"]}'
    )


def test_the_fingerprint_is_twelve_hex_digits_of_the_sha256_of_that_text_and_stays_the_same():
    # echo -n '{"id":"a","text":"水"}' | sha256sum | cut -c1-12
    assert card_fingerprint({"id": "a", "text": "水", "status": "approved"}) == "e1eed5373c08"
    assert len(card_fingerprint(card())) == 12 and card_fingerprint(card()) == card_fingerprint(card())


def test_the_fingerprint_ignores_status_and_follows_everything_the_volunteer_sees():
    base = card()
    assert card_fingerprint({**base, "status": "approved"}) == card_fingerprint(base)
    prints = {
        card_fingerprint(x)
        for x in (
            base, card(text="睡", pinyin="shuì", trad="睡"), card(trad="谁"), card(note="Say it."),
            card(note="Say it.", note_traditional="Say it."), card("r02"),
        )
    }  # fmt: skip
    assert len(prints) == 6


def write(tmp_path, text):
    path = tmp_path / "approvals.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_missing_file_and_a_header_only_file_are_no_approvals(tmp_path):
    assert read_approvals(tmp_path / "nope.csv") == []
    assert read_approvals(write(tmp_path, "card_id,fingerprint,decision,note\n")) == []


def test_rows_are_read_with_their_notes_and_lines(tmp_path):
    path = write(
        tmp_path,
        'card_id,fingerprint,decision,note\ng01-c,0123456789ab,approved,\ng01-e,ba9876543210,rejected,"too rare, ask DJ"\n',
    )
    rows = read_approvals(path)
    assert rows == [
        Approval("g01-c", "0123456789ab", "approved", "", "approvals.csv:2"),
        Approval("g01-e", "ba9876543210", "rejected", "too rare, ask DJ", "approvals.csv:3"),
    ]


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("g01-c,0123456789ab,maybe,", r"approvals\.csv:2: decision must be approved or rejected, not 'maybe'"),
        ("g01-c,0123456789a,approved,", r"approvals\.csv:2: fingerprint must be 12 lowercase hex digits, not '0123456789a'"),
        ("g01-c,0123456789AB,approved,", "fingerprint must be 12 lowercase hex digits"),
        ("g01-c,,approved,", r"approvals\.csv:2: fingerprint is empty"),
    ],
)
def test_a_bad_row_is_an_error_naming_its_line(tmp_path, row, message):
    with pytest.raises(BuildError, match=message):
        read_approvals(write(tmp_path, f"card_id,fingerprint,decision,note\n{row}\n"))


def test_a_card_listed_twice_is_an_error(tmp_path):
    rows = "g01-c,0123456789ab,approved,\ng01-c,ba9876543210,rejected,\n"
    with pytest.raises(BuildError, match=r"approvals\.csv:3: g01-c is already listed at approvals\.csv:2"):
        read_approvals(write(tmp_path, "card_id,fingerprint,decision,note\n" + rows))


def test_writing_keeps_the_order_updates_a_card_in_place_and_adds_new_rows_after(tmp_path):
    a, b, c = (Approval(i, f"{n:012x}", "approved") for n, i in enumerate(["r01", "r02", "r03"], start=1))
    path = tmp_path / "approvals.csv"
    write_approvals(path, [a, b])
    new = [Approval("r02", "aaaaaaaaaaaa", "rejected", "no, too long"), c]
    write_approvals(path, merge(read_approvals(path), new))
    assert path.read_text(encoding="utf-8") == (
        "card_id,fingerprint,decision,note\n"
        "r01,000000000001,approved,\n"
        'r02,aaaaaaaaaaaa,rejected,"no, too long"\n'
        "r03,000000000003,approved,\n"
    )
    assert approvals_text([]) == "card_id,fingerprint,decision,note\n"


def pin(c, decision="approved", where="approvals.csv:2"):
    return Approval(c["id"], card_fingerprint(c), decision, "", where)


def test_an_approval_with_the_cards_fingerprint_approves_it():
    a, b = card("r01"), card("r02", text="睡", pinyin="shuì", trad="睡")
    applied = apply_approvals([a, b], [pin(a)])
    assert [c["status"] for c in applied.cards] == ["approved", "unverified"]
    assert applied.approved == ["r01"] and applied.stale == [] and applied.rejected == []
    assert applied.report_lines() == ["approvals: 1 of 2 cards approved"]
    assert a["status"] == "unverified"  # the cards given are not changed


def test_an_approval_of_a_card_that_has_changed_is_stale_and_the_card_stays_unverified():
    old, new = card("r01"), card("r01", note="Say it twice.")
    applied = apply_approvals([new], [pin(old)])
    assert [c["status"] for c in applied.cards] == ["unverified"] and applied.approved == []
    (stale,) = applied.stale
    assert stale.line() == (
        f"stale approval r01 (approved for {card_fingerprint(old)}, the card is now {card_fingerprint(new)}): "
        "it stays unverified"
    )
    assert applied.report_lines()[1] == f"  {stale.line()}"


def test_a_rejection_with_the_cards_fingerprint_drops_the_card():
    a, b = card("r01"), card("r02", text="睡", pinyin="shuì", trad="睡")
    applied = apply_approvals([a, b], [pin(a, "rejected", "approvals.csv:5")])
    assert [c["id"] for c in applied.cards] == ["r02"] and [r.card_id for r in applied.rejected] == ["r01"]
    assert "  rejected r01 (approvals.csv:5): dropped from the deck" in applied.report_lines()


def test_a_rejection_of_a_card_that_has_changed_is_stale_too_and_the_card_stays():
    old, new = card("r01"), card("r01", note="Fixed.")
    applied = apply_approvals([new], [pin(old, "rejected")])
    assert [c["id"] for c in applied.cards] == ["r01"] and applied.rejected == []
    assert applied.stale[0].line().startswith("stale rejection r01 (rejected for ")


def test_a_row_for_a_card_the_deck_does_not_have_is_an_error_naming_the_line():
    a = card("r01")
    with pytest.raises(BuildError, match=r"approvals\.csv:7: g25-c is not a card of the deck \(delete the row\)"):
        apply_approvals([a], [pin(a), Approval("g25-c", "0123456789ab", "approved", "", "approvals.csv:7")])
