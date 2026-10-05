"""deck_build.error_word: the deliberate-error twin of a phrase, judged by the contract."""

from deck_support import gate_row, needs_c0_fix

from tonekit_harness.deck_build import trial
from tonekit_harness.deck_build.error_word import candidate_positions, derive_error, error_reading
from tonekit_harness.deck_build.lexicon import Lexicon, Variant
from tonekit_harness.deck_build.pairs import pair_cards

SHUI = Variant("水", "shuǐ", "睡", "shuì", "睡", "睡觉", "睡覺", "to sleep", "")
WAN = Variant("碗", "wǎn", "湾", "wān", "灣", "海湾", "海灣", "bay", "")
BA_FOURTH = Variant("把", "bǎ", "爸", "bà", "爸", "爸爸", "爸爸", "dad", "")


def correct_of(text, citation, spoken, trad=None):
    return gate_row(text, citation, spoken, trad).reading


def accept_in_gate(correct):
    def accept(error):
        return trial.problems(list(pair_cards("gate", "p", correct, error, note="")))

    return accept


def test_the_final_noun_is_swapped_and_its_pinyin_spoken_with_sandhi():
    correct = correct_of("一杯水", "yī bēi shuǐ", "yì bēi shuǐ", "一杯水")
    sub, reasons = derive_error(correct, Lexicon([SHUI]), accept_in_gate(correct))
    assert reasons == [] and sub is not None
    assert (sub.error.text, sub.error.citation_pinyin, sub.error.spoken_pinyin) == (
        "一杯睡",
        "yī bēi shuì",
        "yì bēi shuì",
    )
    assert sub.position == 2 and sub.variant is SHUI


def test_the_traditional_text_swaps_the_same_place_with_the_variants_traditional_form():
    correct = correct_of("一碗水", "yī wǎn shuǐ", "yì wán shuǐ", "一碗水")
    sub, _ = derive_error(correct, Lexicon([WAN]), accept_in_gate(correct))
    assert sub is not None and sub.error.text_traditional == "一灣水"


def test_a_noun_that_would_move_the_measure_words_sandhi_is_refused_and_the_measure_word_is_swapped():
    # 一碗水 is yì wán shuǐ; 睡 would make 碗 wǎn again (two surface tones change, R63)
    correct = correct_of("一碗水", "yī wǎn shuǐ", "yì wán shuǐ")
    sub, reasons = derive_error(correct, Lexicon([SHUI, WAN]), accept_in_gate(correct))
    assert sub is not None and sub.error.text == "一湾水" and sub.position == 1
    assert sub.error.spoken_pinyin == "yì wān shuǐ"
    assert len(reasons) == 1
    assert reasons[0].startswith("一碗睡: ") and "in 2 positions" in reasons[0]


def test_without_another_candidate_the_two_tone_error_is_reported_not_made():
    correct = correct_of("一碗水", "yī wǎn shuǐ", "yì wán shuǐ")
    sub, reasons = derive_error(correct, Lexicon([SHUI]), accept_in_gate(correct))
    assert sub is None
    assert any("in 2 positions" in r for r in reasons)
    assert any("碗 has no tone variant" in r for r in reasons)


def test_a_variant_for_another_reading_of_the_character_is_not_used():
    correct = correct_of("一把刀", "yī bà dāo", "yí bà dāo")  # pretend 把 is read bà here
    sub, reasons = derive_error(
        correct, Lexicon([Variant("把", "bǎ", "巴", "bā", "巴", "巴士", "巴士", "bus", "")]), lambda e: []
    )
    assert sub is None
    assert "把 is read bà here but the lexicon's 巴 is for bǎ" in reasons


@needs_c0_fix
def test_a_run_of_three_third_tones_has_no_single_spoken_form():
    # 笑 (xiào) swapped for 晓 (xiǎo) leaves three third tones in a row: 2-2-3 and 3-2-3 are both fine
    correct = correct_of("一小笑伞", "yī xiǎo xiào sǎn", "yì xiǎo xiào sǎn")
    xiao = Variant("笑", "xiào", "晓", "xiǎo", "曉", "晓得", "曉得", "to know", "")
    assert error_reading(correct, 2, xiao) is None
    two = correct_of("一杯伞", "yī bēi sǎn", "yì bēi sǎn")  # a pair of third tones has one reading
    ba = Variant("杯", "bēi", "北", "běi", "北", "北方", "北方", "north", "")
    assert error_reading(two, 1, ba).spoken_pinyin == "yì béi sǎn"  # 北 becomes béi before 伞


def test_candidate_positions_are_the_last_character_then_the_measure_word():
    assert candidate_positions(3) == [2, 1]
    assert candidate_positions(4) == [3, 1]
