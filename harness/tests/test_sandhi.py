"""contracts.sandhi (cmn): the acceptable surface tone sequences of a citation reading."""

import pytest

from tonekit_harness.contracts.pinyin import parse_pinyin
from tonekit_harness.contracts.sandhi import surface_options


def opts(pinyin: str, context: str = "phrase", text: str | None = None) -> set[tuple[str, ...]]:
    syllables = parse_pinyin(pinyin)
    return surface_options([s.tone for s in syllables], [s.base for s in syllables], context, text)


def seq(tones: str) -> set[tuple[str, ...]]:
    return {tuple(tones)}


# ---- 一 ------------------------------------------------------------------------------------

def test_yi_before_tone_1_is_yi4():  # 一杯 yì bēi
    assert opts("yī bēi") == seq("41")


def test_yi_before_tone_4_is_yi2():  # 一块 yí kuài
    assert opts("yī kuài") == seq("24")


@pytest.mark.parametrize("nxt,tone", [("nián", "2"), ("bǎ", "3")])
def test_yi_before_tones_2_and_3_is_yi4(nxt, tone):
    assert opts(f"yī {nxt}") == seq("4" + tone)


def test_yi_alone_stays_yi1():
    assert opts("yī") == seq("1")


def test_yi_at_the_end_stays_yi1():  # 第一 dì yī
    assert opts("dì yī") == seq("41")


def test_an_ordinal_yi_after_di_stays_yi1():  # 第一次 dì yī cì, not dì yí cì
    assert opts("dì yī cì", text="第一次") == seq("414")
    assert opts("dì yī gè", text="第一个") == seq("414")


def test_the_ordinal_needs_the_hanzi_to_show_di():
    assert opts("dì yī cì") == seq("424")  # no text: yi before a 4 is yí
    assert opts("dì yī cì", text="地一次") == seq("424")  # 地 is not 第


def test_yi_after_di_is_ordinal_only_when_di_is_the_syllable_before_it():
    assert opts("dì wǔ yī cì", text="第五一次") == seq("4324")  # not ordinal: 第 is two syllables back


def test_yi_before_a_neutral_tone_is_not_changed():
    assert opts("yī ge") == seq("15")


# ---- 不 ------------------------------------------------------------------------------------

def test_bu_before_tone_4_is_bu2():  # 不对 bú duì
    assert opts("bù duì") == seq("24")


def test_bu_before_other_tones_stays_bu4():  # 不好 bù hǎo (and no T3 sandhi: 不 is not T3)
    assert opts("bù hǎo") == seq("43")
    assert opts("bù chī") == seq("41")
    assert opts("bù lái") == seq("42")


def test_bu_alone_or_final_or_before_neutral_stays_bu4():
    assert opts("bù") == seq("4")
    assert opts("hǎo bù") == seq("34")
    assert opts("bù ma") == seq("45")


def test_yi_before_bu_follows_the_underlying_tone_of_bu():  # 一不对: yí bú duì
    assert opts("yī bù duì") == seq("224")


# ---- third tones ---------------------------------------------------------------------------

def test_two_third_tones():  # 水果 shuí guǒ, 你好 ní hǎo
    assert opts("shuǐ guǒ") == seq("23")
    assert opts("nǐ hǎo") == seq("23")


def test_three_third_tones_accept_both_groupings():  # 展览馆
    assert opts("zhǎn lǎn guǎn") == {("2", "2", "3"), ("3", "2", "3")}


def test_four_third_tones_accept_every_bracketing():
    assert opts("wǒ yě hěn hǎo") == {tuple("2223"), tuple("3223"), tuple("2323")}


def test_a_third_tone_before_another_tone_is_unchanged():
    assert opts("lǎo hǔ chī ròu") == seq("2314")


def test_runs_are_independent_and_mix_with_bu():  # 好久不见 hǎo jiǔ bú jiàn
    assert opts("hǎo jiǔ bù jiàn") == seq("2324")


def test_one_third_tone_alone_is_unchanged():
    assert opts("hǎo") == seq("3")


# ---- a neutral syllable written as neutral keeps the third tone before it (R89) ----------------

@pytest.mark.parametrize("pinyin,text", [
    ("nǎ li", "哪里"), ("jiě jie", "姐姐"), ("nǎi nai", "奶奶"), ("nǐ men", "你们"),
])
def test_a_third_tone_before_a_written_neutral_syllable_stays_3(pinyin, text):
    assert opts(pinyin, text=text) == seq("35")  # exactly one reading: never 2-5


def test_the_underlying_third_tone_of_a_neutral_word_gives_the_regular_sandhi():
    assert opts("nǎ lǐ", text="哪里") == seq("23")  # written 3-3: 2-3, not ná li or nǎ li


def test_a_neutral_reading_is_not_a_citation_reading():
    assert opts("nǎ li", "isolated") == seq("35")
    assert opts("nǎ lǐ", "isolated") == seq("33")


def test_a_neutral_syllable_ends_a_third_tone_run():  # 我们 wǒ men; 你好吗 ní hǎo ma
    assert opts("wǒ men") == seq("35")
    assert opts("nǐ hǎo ma") == seq("235")


def test_other_tones_do_not_neutralise():  # only T3 runs: 大家 dà jiā stays 4-1
    assert opts("dà jiā") == seq("41")


# ---- the isolated (citation) reading --------------------------------------------------------

@pytest.mark.parametrize("pinyin,tones", [
    ("yī bēi", "11"), ("bù duì", "44"), ("shuǐ guǒ", "33"), ("zhǎn lǎn guǎn", "333"), ("yī", "1"),
])
def test_isolated_context_is_only_the_citation_sequence(pinyin, tones):
    assert opts(pinyin, "isolated") == seq(tones)


# ---- homophones: the hanzi text tells 一/不 from 衣/步 -------------------------------------------

def test_without_text_yi1_and_bu4_are_taken_to_be_yi_and_bu():
    assert opts("yī chú") == seq("42")
    assert opts("bù zhòu") == seq("24")


def test_text_keeps_a_homophone_from_sandhi():  # 衣橱 yī chú, 步骤 bù zhòu
    assert opts("yī chú", text="衣橱") == seq("12")
    assert opts("bù zhòu", text="步骤") == seq("44")


def test_text_with_the_real_characters_still_applies_sandhi():
    assert opts("yī chú", text="一橱") == seq("42")
    assert opts("bù duì", text="不对") == seq("24")


def test_punctuation_and_spaces_in_text_are_ignored():
    assert opts("yī bēi shuǐ", text=" 一杯水！") == seq("413")


def test_text_that_does_not_line_up_falls_back_to_the_pinyin():  # 一会儿 yī huìr: 3 hanzi, 2 syllables
    assert opts("yī huìr", text="一会儿") == seq("24")


# ---- bad input ----------------------------------------------------------------------------

def test_tones_and_syllables_must_have_the_same_length():
    with pytest.raises(ValueError, match="2 citation tones but 3 syllables"):
        surface_options(["1", "1"], ["yi", "bei", "shui"], "phrase")


def test_an_unknown_tone_id_is_an_error():
    with pytest.raises(ValueError, match="'6'"):
        surface_options(["1", "6"], ["yi", "bei"], "phrase")


def test_an_unknown_context_is_an_error():
    with pytest.raises(ValueError, match="'solitaire'"):
        surface_options(["1"], ["yi"], "solitaire")
