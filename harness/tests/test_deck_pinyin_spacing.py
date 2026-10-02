"""deck_build.pinyin_spacing: pinyin written in words becomes one syllable per token."""

import pytest

from tonekit_harness.deck_build.pinyin_spacing import space_pinyin, split_token


@pytest.mark.parametrize(
    ("written", "spaced"),
    [
        ("kāfēi", "kā fēi"),
        ("yī bēi kāfēi", "yī bēi kā fēi"),
        ("yìbēishuǐ", "yì bēi shuǐ"),
        ("zhuāngchuáng", "zhuāng chuáng"),
        ("yì bēi shuǐ", "yì bēi shuǐ"),  # already spaced
        ("xi'ān", "xi ān"),  # an apostrophe separates
        ("yi4bei1shui3", "yi4 bei1 shui3"),  # numbered tones
        ("  yī   bēi ", "yī bēi"),
    ],
)
def test_words_are_split_into_syllables(written, spaced):
    assert space_pinyin(written) == spaced


def test_text_that_is_not_pinyin_is_left_for_the_contract_to_name():
    assert space_pinyin("kāfeiq") == "kāfeiq"
    assert split_token("qqq") is None


def test_the_fewest_syllables_win():
    assert split_token("kāfēi") == ["kā", "fēi"]
    assert split_token("shuǐ") == ["shuǐ"]
