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
prompt_note_traditional = ""
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
prompt_note_traditional = "Read it as written: 睡 as in 睡覺."
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
    assert deck.card[1].prompt_note_traditional == "Read it as written: 睡 as in 睡覺."


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


# ---- traditional characters (R74) ---------------------------------------------------------

def tushuguan(**kw) -> dict:  # 图书馆 tú shū guǎn: one native reading
    return card(
        id="z01", set="diag_count", pair=None, text="图书馆", pinyin="tú shū guǎn",
        citation_pinyin="tú shū guǎn",
        intended={"id": "z01", "tones": ["2", "1", "3"], "labels": ["tu", "shu", "guan"]},
        produced_tones=["2", "1", "3"],
    ) | kw


def test_text_traditional_is_optional():
    assert parse_deck(deck_dict()).card[0].text_traditional is None


def test_text_traditional_has_the_length_of_text():
    assert parse_deck(deck_dict(tushuguan(text_traditional="圖書館"))).card[0].text_traditional == "圖書館"


@pytest.mark.parametrize("traditional", ["圖書", "圖書館館"])
def test_a_text_traditional_of_another_length_is_refused(traditional):
    out = problems(deck_dict(tushuguan(text_traditional=traditional)))
    assert f"card 'z01': text_traditional has {len(traditional)} characters but text has 3" in out


def test_text_traditional_cannot_be_blank():
    assert "card 'z01'.text_traditional" in problems(deck_dict(tushuguan(text_traditional=" ")))


def test_prompt_note_traditional_is_optional():
    assert parse_deck(deck_dict()).card[0].prompt_note_traditional is None


def test_prompt_note_traditional_goes_with_a_prompt_note():  # R88
    note = "Read it as written: 睡 as in 睡觉."
    deck = parse_deck(deck_dict(card(), error_card(prompt_note_traditional=note.replace("觉", "覺"))))
    assert deck.card[1].prompt_note_traditional == "Read it as written: 睡 as in 睡覺."
    assert parse_deck(deck_dict(card(prompt_note_traditional=""), error_card())).card[0].prompt_note == ""


@pytest.mark.parametrize("note", ["", "  "])
def test_prompt_note_traditional_without_a_prompt_note_is_refused(note):
    out = problems(deck_dict(card(prompt_note=note, prompt_note_traditional="睡覺"), error_card()))
    assert "card 'g01-c': prompt_note_traditional is set but prompt_note is empty" in out


def test_prompt_note_traditional_on_a_card_with_no_prompt_note_field_is_refused():
    lone = card(prompt_note_traditional="睡覺")
    del lone["prompt_note"]
    assert "card 'g01-c': prompt_note_traditional is set but prompt_note is empty" in problems(deck_dict(lone, error_card()))


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

def test_gate_and_t23_cards_need_a_pair():  # R81: the two sets graded as pairs
    for set_ in ("gate", "diag_t23"):
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
    t23 = [card(id="t-c", set="diag_t23"), error_card(id="t-e", set="diag_t23")]
    assert len(parse_deck(deck_dict(card(), error_card(), *t23)).card) == 4
    half = card(id="t-c", set="diag_t23")  # g01 is complete in gate, but not in diag_t23
    assert "pair 'g01' (set diag_t23) has 1 correct and 0 tone_error" in problems(
        deck_dict(card(), error_card(), half)
    )


@pytest.mark.parametrize("set_", ["quiet", "diag_count", "register"])
def test_pairs_only_group_outside_the_pair_sets(set_):  # R81: no completeness check there
    two_errors = [error_card(id=f"x{i}", set=set_) for i in range(2)]
    assert len(parse_deck(deck_dict(*two_errors)).card) == 2
    assert parse_deck(deck_dict(card(id="lone", set=set_))).card[0].pair == "g01"


# ---- the diag sets (R76, R81) ---------------------------------------------------------------

def mai(id_, word, tones, text, pinyin, others, **kw) -> dict:
    """A one-syllable minimal-set card (买 mǎi / 卖 mài); `others` are its distractors' (id, tones)."""
    return card(
        id=id_, set="diag_minimal", pair="m01", text=text, pinyin=pinyin, citation_pinyin=pinyin,
        context="isolated", intended={"id": word, "tones": tones, "labels": ["mai"]},
        produced_tones=tones,
        distractors=[{"id": i, "tones": t, "labels": ["mai"]} for i, t in others],
    ) | kw


def mai_pair() -> list[dict]:
    return [
        mai("m01-a", "mai3", ["3"], "买", "mǎi", [("mai4", ["4"])]),
        mai("m01-b", "mai4", ["4"], "卖", "mài", [("mai3", ["3"])]),
    ]


def test_a_minimal_set_of_correct_cards_that_name_each_other_loads():
    assert len(parse_deck(deck_dict(*mai_pair())).card) == 2


def test_minimal_cards_need_no_pair():
    cards = [c | {"pair": None} for c in mai_pair()]
    assert len(parse_deck(deck_dict(*cards)).card) == 2


def test_a_minimal_card_is_a_correct_reading():
    bad = mai("m01-b", "mai4", ["4"], "卖", "mǎi", [("mai3", ["3"])], label="tone_error")
    out = problems(deck_dict(mai_pair()[0], bad))
    assert "card 'm01-b': set 'diag_minimal' cards must be correct readings, not tone_error" in out


def test_a_minimal_card_needs_a_distractor():
    out = problems(deck_dict(mai_pair()[0], mai("m01-b", "mai4", ["4"], "卖", "mài", [])))
    assert "card 'm01-b': a diag_minimal card needs a distractor that is another diag_minimal card's intended id" in out


def test_a_minimal_distractor_must_be_another_cards_intended_id():
    lost = mai("m01-b", "mai4", ["4"], "卖", "mài", [("mai1", ["1"])])
    out = problems(deck_dict(mai_pair()[0], lost))
    assert "card 'm01-b': a diag_minimal card needs a distractor" in out and "'mai1'" in out


def test_a_minimal_distractor_cannot_be_the_cards_own_intended_id():
    selfish = mai("m01-b", "mai4", ["4"], "卖", "mài", [("mai4", ["4"])])
    assert "card 'm01-b': a diag_minimal card needs a distractor" in problems(deck_dict(mai_pair()[0], selfish))


def test_one_matching_distractor_among_others_is_enough():
    cards = [
        mai("m01-a", "mai3", ["3"], "买", "mǎi", [("mai4", ["4"]), ("mai1", ["1"])]),
        mai("m01-b", "mai4", ["4"], "卖", "mài", [("mai1", ["1"]), ("mai3", ["3"])]),
    ]
    assert len(parse_deck(deck_dict(*cards)).card) == 2


def test_only_diag_minimal_cards_count_as_other_members():
    elsewhere = mai("m01-b", "mai4", ["4"], "卖", "mài", [("mai3", ["3"])], set="diag_count")
    assert "card 'm01-a': a diag_minimal card needs a distractor" in problems(
        deck_dict(mai_pair()[0], elsewhere)
    )


def context_card(id_, text, pinyin, citation, tones, context, **kw) -> dict:
    return card(
        id=id_, set="diag_context", pair=None, text=text, pinyin=pinyin, citation_pinyin=citation,
        context=context, intended={"id": id_, "tones": tones, "labels": ["yi", "bei"][: len(tones)]},
        produced_tones=tones,
    ) | kw


def test_a_context_set_contrasts_the_citation_and_the_sandhi_reading():  # 一 / 一杯
    alone = context_card("c01-iso", "一", "yī", "yī", ["1"], "isolated")
    phrase = context_card("c01-phr", "一杯", "yì bēi", "yī bēi", ["4", "1"], "phrase")
    assert [c.context for c in parse_deck(deck_dict(alone, phrase)).card] == ["isolated", "phrase"]


def test_a_context_card_is_a_correct_reading():
    bad = context_card("c01-phr", "一杯", "yì bēi", "yī bēi", ["4", "1"], "phrase", label="tone_error")
    assert "card 'c01-phr': set 'diag_context' cards must be correct readings, not tone_error" in problems(
        deck_dict(bad)
    )


def test_context_cards_need_no_distractors_or_pair():
    lone = context_card("c02", "水果", "shuí guǒ", "shuǐ guǒ", ["2", "3"], "phrase")
    assert parse_deck(deck_dict(lone)).card[0].distractors == []


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


def zhanlanguan(**kw) -> dict:  # 展览馆 zhǎn lǎn guǎn: 2-2-3 or 3-2-3
    return card(
        id="z01", set="diag_count", pair=None, text="展览馆", pinyin="zhán lán guǎn",
        citation_pinyin="zhǎn lǎn guǎn",
        intended={"id": "z01", "tones": ["2", "2", "3"], "labels": ["zhan", "lan", "guan"]},
        produced_tones=["2", "2", "3"],
    ) | kw


def test_a_third_tone_run_read_unchanged_is_refused():
    lone = zhanlanguan(pinyin="zhǎn lǎn guǎn", produced_tones=["3", "3", "3"])
    lone["intended"] = {"id": "z01", "tones": ["3", "3", "3"], "labels": ["zhan", "lan", "guan"]}
    out = problems(deck_dict(lone))
    assert "phrase reading 3-3-3 is not a sandhi reading of 'zhǎn lǎn guǎn'" in out
    assert "2-2-3 or 3-2-3" in out


def test_a_correct_card_needs_one_native_reading():  # 展览馆 is 2-2-3 or 3-2-3 (R89)
    out = problems(deck_dict(zhanlanguan()))
    assert "card 'z01': has 2 native readings (2-2-3, 3-2-3); a correct card needs one (R89)" in out


def test_a_correct_card_with_two_groupings_inside_a_phrase_is_refused():  # 一把雨伞 yì bá yú sǎn
    umbrella = card(
        id="u01", set="diag_count", pair=None, text="一把雨伞", pinyin="yì bá yú sǎn",
        citation_pinyin="yī bǎ yǔ sǎn",
        intended={"id": "u01", "tones": ["4", "2", "2", "3"], "labels": ["yi", "ba", "yu", "san"]},
        produced_tones=["4", "2", "2", "3"],
    )
    out = problems(deck_dict(umbrella))
    assert "card 'u01': has 2 native readings (4-2-2-3, 4-3-2-3); a correct card needs one (R89)" in out


def test_a_correct_card_with_one_reading_is_accepted():  # 一杯水 yì bēi shuǐ
    assert parse_deck(deck_dict()).card[0].label == "correct"
    assert parse_deck(deck_dict(tushuguan())).card[0].produced_tones == ["2", "1", "3"]


def test_an_error_card_may_have_several_native_readings():
    # 土鼠管 tǔ shǔ guǎn is 2-2-3 or 3-2-3; its twin 图书馆 (2-1-3) carries the one-reading guarantee
    error = tushuguan(
        id="z01-e", label="tone_error", text="土鼠管", pinyin="tú shú guǎn",
        citation_pinyin="tǔ shǔ guǎn", produced_tones=["2", "2", "3"],
    )
    assert parse_deck(deck_dict(tushuguan(id="z01-c"), error)).card[1].label == "tone_error"


@pytest.mark.parametrize("pinyin,tones,refused", [
    ("nǎ li", ["3", "5"], False), ("ná li", ["2", "5"], True), ("ná lǐ", ["2", "3"], True),
])
def test_a_written_neutral_syllable_keeps_the_third_tone_before_it(pinyin, tones, refused):  # 哪里 nǎ li
    lone = card(
        id="n01", set="diag_count", pair=None, text="哪里", pinyin=pinyin, citation_pinyin="nǎ li",
        intended={"id": "n01", "tones": tones, "labels": ["na", "li"]}, produced_tones=tones,
    )
    if refused:
        assert f"phrase reading {'-'.join(tones)} is not a sandhi reading of 'nǎ li' (3-5)" in problems(deck_dict(lone))
    else:
        assert parse_deck(deck_dict(lone)).card[0].produced_tones == tones


def test_an_ordinal_yi_after_di_stays_yi1():  # 第一次 dì yī cì
    lone = card(
        id="o01", set="diag_count", pair=None, text="第一次", pinyin="dì yī cì", citation_pinyin="dì yī cì",
        intended={"id": "o01", "tones": ["4", "1", "4"], "labels": ["di", "yi", "ci"]},
        produced_tones=["4", "1", "4"],
    )
    assert parse_deck(deck_dict(lone)).card[0].produced_tones == ["4", "1", "4"]
    unmarked = lone | {"text": "地一次"}  # 地 is not 第: 一 is the plain 一 and goes to yí
    assert "phrase reading 4-1-4 is not a sandhi reading" in problems(deck_dict(unmarked))


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
