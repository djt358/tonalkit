"""deck_build.single_cards, minimal_set and t23_set: the sets that are not made from the lexicon."""

import pytest
from deck_support import needs_c0_fix

from tonekit_harness.deck_build import trial
from tonekit_harness.deck_build.errors import BuildError
from tonekit_harness.deck_build.minimal_set import minimal_cards, numbered
from tonekit_harness.deck_build.single_cards import single_cards
from tonekit_harness.deck_build.t23_set import changed_character, t23_cards


def csv(tmp_path, text, name="s.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_repeated_row_becomes_that_many_numbered_cards(tmp_path):
    path = csv(tmp_path, "text,citation_pinyin,spoken_pinyin,repeat,note\n妈麻马骂,mā má mǎ mà,mā má mǎ mà,3,Pause.\n")
    cards, flags = single_cards(path, set_="register", prefix="r", context="isolated")
    assert [c["id"] for c in cards] == ["r01", "r02", "r03"] and flags == {}
    assert cards[0]["context"] == "isolated" and cards[0]["produced_tones"] == ["1", "2", "3", "4"]
    assert cards[0]["intended"] == {"id": "r01", "tones": ["1", "2", "3", "4"], "labels": ["ma"] * 4}
    assert cards[2]["prompt_note"] == "Pause." and cards[2]["label"] == "correct"
    assert trial.problems(cards) == []


def test_a_hesitation_card_asks_only_for_the_tones_of_the_spell(tmp_path):
    path = csv(tmp_path, "text,citation_pinyin,spoken_pinyin,flag\n嗯…一杯水,yī bēi shuǐ,yì bēi shuǐ,look at me\n")
    (card,), flags = single_cards(path, set_="diag_count", prefix="n", context="phrase")
    assert (card["text"], card["pinyin"], card["produced_tones"]) == ("嗯…一杯水", "yì bēi shuǐ", ["4", "1", "3"])
    assert flags == {"n01": "look at me"}
    assert trial.problems([card]) == []


def test_a_context_the_row_gives_wins_and_a_bad_one_names_its_line(tmp_path):
    path = csv(
        tmp_path, "text,citation_pinyin,spoken_pinyin,context\n水,shuǐ,shuǐ,isolated\n水果,shuǐ guǒ,shuí guǒ,phrase\n"
    )
    cards, _ = single_cards(path, set_="register", prefix="x", context=None)
    assert [c["context"] for c in cards] == ["isolated", "phrase"]
    assert trial.problems(cards) == []  # 水果 spoken shuí guǒ is its sandhi
    with pytest.raises(BuildError, match=r"s\.csv:2: context must be phrase or isolated, not ''"):
        single_cards(
            csv(tmp_path, "text,citation_pinyin,spoken_pinyin\n水,shuǐ,shuǐ\n"),
            set_="register",
            prefix="x",
            context=None,
        )
    with pytest.raises(BuildError, match="repeat must be a whole number"):
        single_cards(
            csv(tmp_path, "text,citation_pinyin,spoken_pinyin,repeat\n水,shuǐ,shuǐ,0\n"),
            set_="register",
            prefix="x",
            context="isolated",
        )


@needs_c0_fix
def test_a_card_whose_spoken_pinyin_keeps_the_citation_tone_is_refused_by_the_contract(tmp_path):
    path = csv(tmp_path, "text,citation_pinyin,spoken_pinyin,context\n水果,shuǐ guǒ,shuǐ guǒ,phrase\n")
    cards, _ = single_cards(path, set_="register", prefix="x", context=None)
    (problem,) = trial.problems(cards)
    assert "phrase reading 3-3 is not a sandhi reading of 'shuǐ guǒ' (2-3)" in problem


def test_a_word_is_named_by_its_numbered_pinyin():
    assert numbered("mǎi") == "mai3" and numbered("yì bēi shuǐ") == "yi4bei1shui3" and numbered("lüè") == "lüe4"


MINIMAL = (
    "group,text,text_traditional,pinyin\nm01,买,買,mǎi\nm01,卖,賣,mài\nm02,水,水,shuǐ\nm02,睡,睡,shuì\nm02,谁,誰,shuí\n"
)


def test_every_word_of_a_minimal_set_is_correct_and_lists_the_others_as_distractors(tmp_path):
    cards, _ = minimal_cards(csv(tmp_path, MINIMAL))
    assert [c["id"] for c in cards] == ["m01-a", "m01-b", "m02-a", "m02-b", "m02-c"]
    assert {c["label"] for c in cards} == {"correct"} and {c["pair"] for c in cards} == {"m01", "m02"}
    a = cards[0]
    assert a["intended"] == {"id": "mai3", "tones": ["3"], "labels": ["mai"]}
    assert a["distractors"] == [{"id": "mai4", "tones": ["4"], "labels": ["mai"]}]
    assert [d["id"] for d in cards[2]["distractors"]] == ["shui4", "shui2"]  # a set of three
    assert all(c["context"] == "isolated" and c["produced_tones"] == c["intended"]["tones"] for c in cards)


@needs_c0_fix
def test_the_contract_takes_a_minimal_set_as_it_is(tmp_path):
    cards, _ = minimal_cards(csv(tmp_path, MINIMAL))
    assert trial.problems(cards) == []


def test_a_minimal_set_needs_two_different_words(tmp_path):
    with pytest.raises(BuildError, match="set m01 has one word"):
        minimal_cards(csv(tmp_path, "group,text,pinyin\nm01,买,mǎi\n"))
    with pytest.raises(BuildError, match="lists the same word twice"):
        minimal_cards(csv(tmp_path, "group,text,pinyin\nm01,买,mǎi\nm01,买,mǎi\n"))


T23 = (
    "text,citation_pinyin,spoken_pinyin,error_text,error_citation_pinyin,error_spoken_pinyin,as_in,gloss\n"
    "起床,qǐ chuáng,qǐ chuáng,骑床,qí chuáng,qí chuáng,骑车,to ride a bike\n"
)


def test_a_t23_pair_names_the_one_changed_character_in_its_note(tmp_path):
    cards, _ = t23_cards(csv(tmp_path, T23))
    c, e = cards
    assert (c["id"], e["id"], c["pair"], e["pair"]) == ("t01-c", "t01-e", "t01", "t01")
    assert e["prompt_note"] == "Read it as written: 骑 as in 骑车 (to ride a bike)."
    assert (c["produced_tones"], e["produced_tones"]) == (["3", "2"], ["2", "2"])
    assert trial.problems(cards) == []


def test_a_t23_error_must_differ_in_exactly_one_character(tmp_path):
    assert changed_character("起床", "骑床", "w") == "骑"
    for error in ("起床", "骑窗"):
        with pytest.raises(BuildError, match=r"differ in [02] characters; it must be one"):
            changed_character("起床", error, "s.csv:2")
    with pytest.raises(BuildError, match="differ in length"):
        changed_character("起床", "起", "w")


def test_a_t23_error_that_changes_two_surface_tones_is_refused_by_the_contract(tmp_path):
    # 买米 is mái mǐ (third-tone sandhi); 买蜜 is mǎi mì: the sandhi moves as well, two tones change
    both = T23.replace(
        "起床,qǐ chuáng,qǐ chuáng,骑床,qí chuáng,qí chuáng,骑车", "买米,mǎi mǐ,mái mǐ,买蜜,mǎi mì,mǎi mì,蜜蜂"
    )
    cards, _ = t23_cards(csv(tmp_path, both))
    (problem,) = trial.problems(cards)
    assert "differ from intended in 2 positions" in problem and "it needs exactly one" in problem


def test_a_note_that_names_characters_needs_a_traditional_version(tmp_path):
    head = "text,text_traditional,citation_pinyin,spoken_pinyin,note,note_traditional\n"
    with pytest.raises(BuildError, match=r"s\.csv:2: the note names characters, so it needs a traditional version"):
        single_cards(csv(tmp_path, head + "一本书,一本書,yī běn shū,yì běn shū,Stop after 一本.,\n"), set_="diag_count", prefix="n", context="phrase")
    (card,), _ = single_cards(
        csv(tmp_path, head + "一本书,一本書,yī běn shū,yì běn shū,Say 一本书.,Say 一本書.\n"),
        set_="diag_count", prefix="n", context="phrase",
    )  # fmt: skip
    assert list(card)[-3:] == ["prompt_note", "prompt_note_traditional", "status"]
    assert (card["prompt_note"], card["prompt_note_traditional"]) == ("Say 一本书.", "Say 一本書.")
    (plain,), _ = single_cards(
        csv(tmp_path, head + "水,水,shuǐ,shuǐ,Say it alone.,\n", "p.csv"), set_="register", prefix="x", context="isolated"
    )  # fmt: skip
    assert "prompt_note_traditional" not in plain  # no characters named, nothing to write twice


def test_the_note_of_a_t23_error_is_also_written_in_traditional_characters(tmp_path):
    traditional = T23.replace("text,", "text_traditional,error_text_traditional,as_in_traditional,text,", 1).replace(
        "起床,qǐ chuáng", "起床,騎床,騎車,起床,qǐ chuáng", 1
    )
    cards, _ = t23_cards(csv(tmp_path, traditional))
    assert cards[1]["prompt_note"] == "Read it as written: 骑 as in 骑车 (to ride a bike)."
    assert cards[1]["prompt_note_traditional"] == "Read it as written: 騎 as in 騎車 (to ride a bike)."
    assert "prompt_note_traditional" not in cards[0]


def test_the_words_of_a_minimal_set_must_share_their_toneless_syllables(tmp_path):
    with pytest.raises(BuildError) as e:
        minimal_cards(csv(tmp_path, "group,text,pinyin\nm01,买,mǎi\nm01,汤,tāng\n"))
    assert "s.csv:2: set m01 mixes syllables: 买 (mai), 汤 (tang)" in str(e.value)
    with pytest.raises(BuildError, match=r"s\.csv:3: pinyin: "):
        minimal_cards(csv(tmp_path, "group,text,pinyin\nm01,买,mǎi\nm01,卖,mài!\n"))
    assert len(minimal_cards(csv(tmp_path, "group,text,pinyin\nm01,鞋,xié\nm01,谢,xiè\n"))[0]) == 2
