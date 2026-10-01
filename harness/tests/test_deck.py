"""contracts.deck: every rule of contracts.md section 1, one test each."""

import copy
import hashlib

import pytest

from tonekit_harness.contracts.deck import Deck, DeckError, deck_sha256, load_deck, parse_deck

EXAMPLE_TOML = """\
[deck]
id = "s05-v1"
lect = "cmn"
version = 1
title = "Mandarin tones: phrases and words"

[[card]]
id = "g01-c"
set = "gate"
pair = "g01"
label = "correct"
text = "一杯水"
pinyin = "yì bēi shuǐ"
citation_pinyin = "yī bēi shuǐ"
context = "phrase"
intended = { id = "g01", tones = ["4", "1", "3"], labels = ["yi", "bei", "shui"] }
produced_tones = ["4", "1", "3"]
distractors = []
prompt_note = ""
status = "unverified"

[[card]]
id = "g01-e"
set = "gate"
pair = "g01"
label = "tone_error"
text = "一杯睡"
pinyin = "yì bēi shuì"
citation_pinyin = "yī bēi shuì"
context = "phrase"
intended = { id = "g01", tones = ["4", "1", "3"], labels = ["yi", "bei", "shui"] }
produced_tones = ["4", "1", "4"]
prompt_note = "Read it as written: 睡 as in 睡觉."
status = "unverified"
"""


def card(**kw) -> dict:
    base = {
        "id": "g01-c", "set": "gate", "pair": "g01", "label": "correct", "text": "一杯水",
        "pinyin": "yì bēi shuǐ", "citation_pinyin": "yī bēi shuǐ", "context": "phrase",
        "intended": {"id": "g01", "tones": ["4", "1", "3"], "labels": ["yi", "bei", "shui"]},
        "produced_tones": ["4", "1", "3"], "distractors": [], "prompt_note": "",
        "status": "unverified",
    }
    base.update(kw)
    return base


def error_card(**kw) -> dict:
    return card(
        id="g01-e", label="tone_error", text="一杯睡", pinyin="yì bēi shuì",
        citation_pinyin="yī bēi shuì", produced_tones=["4", "1", "4"],
        prompt_note="Read it as written: 睡 as in 睡觉.",
    ) | kw


def deck_dict(*cards: dict) -> dict:
    return {
        "deck": {"id": "s05-v1", "lect": "cmn", "version": 1, "title": "Test deck"},
        "card": list(cards) or [card(), error_card()],
    }


def problems(data: dict, **kw) -> str:
    with pytest.raises(DeckError) as e:
        parse_deck(data, **kw)
    return str(e.value)


def test_the_contracts_example_loads(tmp_path):
    path = tmp_path / "s05-v1.toml"
    path.write_text(EXAMPLE_TOML, encoding="utf-8")
    deck = load_deck(path)
    assert isinstance(deck, Deck)
    assert deck.deck.id == "s05-v1" and [c.id for c in deck.card] == ["g01-c", "g01-e"]
    assert deck.card[1].prompt_note.startswith("Read it as written")


def test_deck_sha256_is_the_hash_of_the_file_bytes(tmp_path):
    path = tmp_path / "d.toml"
    path.write_text(EXAMPLE_TOML, encoding="utf-8")
    assert deck_sha256(path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_invalid_toml_names_the_file(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[deck\n", encoding="utf-8")
    with pytest.raises(DeckError, match="bad.toml: invalid TOML"):
        load_deck(path)


def test_the_error_names_the_file(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text(EXAMPLE_TOML.replace('lect = "cmn"', 'lect = "yue"'), encoding="utf-8")
    with pytest.raises(DeckError, match="bad.toml"):
        load_deck(path)


# ---- fields ---------------------------------------------------------------------------------

@pytest.mark.parametrize("field,value", [
    ("set", "gate2"), ("label", "wrong"), ("context", "solitaire"), ("status", "audited"),
])
def test_enum_fields_reject_unknown_values(field, value):
    out = problems(deck_dict(card(**{field: value}), error_card()))
    assert f"card 'g01-c'.{field}" in out


@pytest.mark.parametrize("bad_id", ["G01-c", "g01_c", "g01 c", "", "g01-é"])
def test_card_ids_are_lowercase_alphanumeric_and_dashes(bad_id):
    assert "id" in problems(deck_dict(card(id=bad_id), error_card()))


def test_card_ids_are_unique():
    out = problems(deck_dict(card(), error_card(id="g01-c")))
    assert "duplicate card id 'g01-c'" in out


def test_unknown_card_fields_are_errors():
    assert "distractor" in problems(deck_dict(card(distractor=[]), error_card()))


def test_unknown_deck_sections_are_errors():
    data = deck_dict()
    data["cards"] = []
    assert "cards" in problems(data)


def test_an_empty_text_is_an_error():
    assert "card 'g01-c'.text" in problems(deck_dict(card(text=" "), error_card()))


def test_a_deck_needs_cards():
    data = deck_dict()
    data["card"] = []
    assert "at least 1 item" in problems(data)


# ---- tones and lengths ----------------------------------------------------------------------

def test_intended_labels_match_the_tones():
    bad = card(intended={"id": "g01", "tones": ["4", "1", "3"], "labels": ["yi", "bei"]})
    out = problems(deck_dict(bad, error_card()))
    assert "card 'g01-c': intended has 3 tones but 2 labels" in out


def test_distractor_labels_match_the_tones():
    bad = card(distractors=[{"id": "d", "tones": ["4", "1", "3"], "labels": ["a"]}])
    assert "card 'g01-c': distractor 'd' has 3 tones but 1 labels" in problems(
        deck_dict(bad, error_card())
    )


def test_intended_needs_tones():
    empty = card(intended={"id": "g01", "tones": [], "labels": []}, produced_tones=[])
    assert "card 'g01-c': intended has no tones" in problems(deck_dict(empty, error_card()))


def test_produced_tones_have_the_intended_length():
    out = problems(deck_dict(card(), error_card(produced_tones=["4", "1"])))
    assert "card 'g01-e': produced_tones has 2 tones but intended has 3" in out


@pytest.mark.parametrize("where", ["intended", "produced", "distractor"])
def test_tones_are_pack_tone_ids(where):
    tones = ["4", "1", "9"]
    if where == "intended":
        intended = {"id": "g01", "tones": tones, "labels": ["a", "b", "c"]}
        bad = [card(intended=intended, produced_tones=tones), error_card()]
    elif where == "produced":
        bad = [card(), error_card(produced_tones=tones)]
    else:
        bad = [card(distractors=[{"id": "d", "tones": tones, "labels": ["a", "b", "c"]}]), error_card()]
    out = problems(deck_dict(*bad))
    assert "'9' is not a tone id of the pack" in out


def test_the_inventory_comes_from_the_pack_passed_in(tmp_path):
    pack = tmp_path / "pack.toml"
    pack.write_text(
        '[pack]\nlect = "cmn"\n' + "".join(f'[[tone]]\nid = "{i}"\n' for i in "1234"),
        encoding="utf-8",
    )
    neutral = card(
        id="n01", set="register", pair=None, label="n/a", text="吗", pinyin="ma", citation_pinyin="ma",
        context="isolated", intended={"id": "n01", "tones": ["5"], "labels": ["ma"]},
        produced_tones=["5"],
    )
    assert parse_deck(deck_dict(neutral)).card[0].id == "n01"
    assert "'5' is not a tone id of the pack" in problems(deck_dict(neutral), pack=pack)


def test_the_deck_lect_must_be_the_packs(tmp_path):
    pack = tmp_path / "pack.toml"
    pack.write_text('[pack]\nlect = "yue"\n[[tone]]\nid = "1"\n', encoding="utf-8")
    assert "deck lect 'cmn' but the pack is for 'yue'" in problems(deck_dict(), pack=pack)


def test_a_lect_without_rules_is_an_error(tmp_path):
    pack = tmp_path / "pack.toml"
    pack.write_text('[pack]\nlect = "yue"\n[[tone]]\nid = "1"\n', encoding="utf-8")
    data = deck_dict()
    data["deck"]["lect"] = "yue"
    assert "no rules for lect 'yue'" in problems(data, pack=pack)


# ---- correct / tone_error -------------------------------------------------------------------

def test_a_correct_card_produces_the_intended_tones():
    out = problems(deck_dict(card(produced_tones=["4", "1", "4"], pinyin="yì bēi shuì"), error_card()))
    assert "card 'g01-c': label is correct but produced_tones 4-1-4 differ from intended 4-1-3" in out


@pytest.mark.parametrize("produced,count", [(["4", "1", "3"], 0), (["4", "2", "4"], 2)])
def test_a_tone_error_differs_in_exactly_one_position(produced, count):
    bad = error_card(produced_tones=produced, pinyin="yì bēi shuǐ" if count == 0 else "yì bái shuì")
    out = problems(deck_dict(card(), bad))
    assert f"card 'g01-e': label is tone_error but produced_tones differ from intended in {count}" in out


# ---- pairs ----------------------------------------------------------------------------------

def test_gate_and_diag_cards_need_a_pair():
    for set_ in ("gate", "diag_t23", "diag_minimal"):
        out = problems(deck_dict(card(set=set_, pair=None), error_card(set=set_)))
        assert f"card 'g01-c': set {set_!r} needs a pair" in out


def test_other_sets_may_leave_the_pair_out():
    lone = card(id="c01", set="diag_count", pair=None)
    assert parse_deck(deck_dict(lone)).card[0].pair is None


def test_a_pair_with_only_a_correct_card():
    out = problems(deck_dict(card()))
    assert "pair 'g01' (set gate) has 1 correct and 0 tone_error cards; it needs one of each" in out


def test_a_pair_with_two_correct_cards():
    out = problems(deck_dict(card(), card(id="g01-d"), error_card()))
    assert "pair 'g01' (set gate) has 2 correct and 1 tone_error cards" in out


def test_a_pair_with_two_errors():
    out = problems(deck_dict(card(), error_card(), error_card(id="g01-f")))
    assert "pair 'g01' (set gate) has 1 correct and 2 tone_error cards" in out


def test_an_n_a_card_cannot_be_in_a_pair():
    out = problems(deck_dict(card(), error_card(), card(id="g01-n", label="n/a")))
    assert "pair 'g01' (set gate) has an n/a card: g01-n" in out


def test_a_pair_shares_its_intended_reading():
    other = {"id": "g01", "tones": ["4", "1", "2"], "labels": ["yi", "bei", "shui"]}
    out = problems(deck_dict(card(), error_card(intended=other, produced_tones=["4", "1", "4"])))
    assert "pair 'g01' (set gate): g01-e intends 4-1-2 but g01-c intends 4-1-3" in out


def test_the_same_pair_id_in_two_sets_is_two_pairs():
    quiet = [card(id="q-c", set="quiet"), error_card(id="q-e", set="quiet")]
    assert len(parse_deck(deck_dict(card(), error_card(), *quiet)).card) == 4


# ---- sandhi and the displayed reading -------------------------------------------------------

def test_a_phrase_card_must_apply_sandhi():  # 一杯水 read yī bēi shuǐ
    wrong = card(
        intended={"id": "g01", "tones": ["1", "1", "3"], "labels": ["yi", "bei", "shui"]},
        produced_tones=["1", "1", "3"], pinyin="yī bēi shuǐ",
    )
    wrong_error = error_card(
        intended={"id": "g01", "tones": ["1", "1", "3"], "labels": ["yi", "bei", "shui"]},
        produced_tones=["1", "1", "4"], pinyin="yī bēi shuì",
    )
    out = problems(deck_dict(wrong, wrong_error))
    assert "card 'g01-c': phrase reading 1-1-3 is not a sandhi reading of 'yī bēi shuǐ' (4-1-3)" in out


def test_an_isolated_card_must_not_apply_sandhi():  # 一 alone is yī; 一杯 isolated is not sandhi
    iso = card(
        id="i01", set="register", pair=None, label="n/a", text="一杯", pinyin="yì bēi",
        citation_pinyin="yī bēi", context="isolated",
        intended={"id": "i01", "tones": ["4", "1"], "labels": ["yi", "bei"]},
        produced_tones=["4", "1"],
    )
    out = problems(deck_dict(iso))
    assert "card 'i01': isolated reading 4-1 is not the citation tones of 'yī bēi' (1-1)" in out


def test_isolated_citation_and_alone_cards_pass():
    alone = card(
        id="i02", set="register", pair=None, label="n/a", text="一", pinyin="yī", citation_pinyin="yī",
        context="isolated", intended={"id": "i02", "tones": ["1"], "labels": ["yi"]},
        produced_tones=["1"],
    )
    assert parse_deck(deck_dict(alone)).card[0].context == "isolated"


@pytest.mark.parametrize("tones,pinyin", [
    (["2", "2", "3"], "zhán lán guǎn"), (["3", "2", "3"], "zhǎn lán guǎn"),
])
def test_third_tone_runs_accept_either_grouping(tones, pinyin):  # 展览馆
    lone = card(
        id="z01", set="diag_count", pair=None, text="展览馆", pinyin=pinyin,
        citation_pinyin="zhǎn lǎn guǎn",
        intended={"id": "z01", "tones": tones, "labels": ["zhan", "lan", "guan"]},
        produced_tones=tones,
    )
    assert parse_deck(deck_dict(lone)).card[0].produced_tones == tones


def test_a_third_tone_run_read_unchanged_is_refused():
    lone = card(
        id="z01", set="diag_count", pair=None, text="展览馆", pinyin="zhǎn lǎn guǎn",
        citation_pinyin="zhǎn lǎn guǎn",
        intended={"id": "z01", "tones": ["3", "3", "3"], "labels": ["zhan", "lan", "guan"]},
        produced_tones=["3", "3", "3"],
    )
    assert "2-2-3 or 3-2-3" in problems(deck_dict(lone))


def test_an_error_card_is_checked_against_its_own_citation_pinyin():
    # 衣杯水 (yī, not 一) is read yī bēi shuǐ with no sandhi: 1-1-3 differs from 4-1-3 in one place
    homophone = error_card(
        text="衣杯水", pinyin="yī bēi shuǐ", citation_pinyin="yī bēi shuǐ", produced_tones=["1", "1", "3"],
    )
    assert parse_deck(deck_dict(card(), homophone)).card[1].text == "衣杯水"


def test_the_pinyin_shows_what_the_card_asks_for():
    out = problems(deck_dict(card(pinyin="yī bēi shuǐ"), error_card()))
    assert "card 'g01-c': pinyin is 1-1-3 but produced_tones are 4-1-3" in out


def test_citation_pinyin_has_one_syllable_per_tone():
    out = problems(deck_dict(card(citation_pinyin="yī bēi"), error_card()))
    assert "card 'g01-c': citation_pinyin has 2 syllables but intended has 3 tones" in out


@pytest.mark.parametrize("field", ["pinyin", "citation_pinyin"])
def test_bad_pinyin_names_the_card_and_the_syllable(field):
    out = problems(deck_dict(card(**{field: "yì bēi shuuǐ"}), error_card()))
    assert f"card 'g01-c': {field}: bad pinyin syllable 'shuuǐ'" in out


def test_all_problems_are_reported_together():
    out = problems(deck_dict(card(pinyin="yī bēi shuǐ"), error_card(pinyin="yī bēi shuì")))
    assert "card 'g01-c'" in out and "card 'g01-e'" in out


def test_models_validate_without_the_loader():
    assert Deck.model_validate(copy.deepcopy(deck_dict())).deck.version == 1
