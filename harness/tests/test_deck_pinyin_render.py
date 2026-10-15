"""deck_build.pinyin_render: tone-marked pinyin, read back by the contract's own parser."""

import pytest

from tonekit_harness.contracts.pinyin import parse_pinyin
from tonekit_harness.deck_build.pinyin_render import render, render_syllable

BASES = [
    "a", "o", "e", "er", "ai", "ei", "ao", "ou", "ie", "uo", "ui", "iu", "wan", "yi", "bei", "shui",
    "xiong", "jiu", "guo", "zhi", "dian", "liang", "kuai", "chuang", "zhuang", "lüe", "nü", "mao", "qiao",
]  # fmt: skip


@pytest.mark.parametrize("base", BASES)
def test_every_rendering_reads_back_as_the_same_syllable_and_tone(base):
    for tone in "12345":
        (syllable,) = parse_pinyin(render_syllable(base, tone))
        assert (syllable.base, syllable.tone) == (base, tone)


@pytest.mark.parametrize(
    ("base", "tone", "marked"),
    [("shui", "3", "shuǐ"), ("liang", "4", "liàng"), ("jiu", "3", "jiǔ"), ("hui", "2", "huí"),
     ("guo", "3", "guǒ"), ("ou", "1", "ōu"), ("lüe", "4", "lüè"), ("nü", "3", "nǚ"), ("ma", "5", "ma")],
)  # fmt: skip
def test_the_mark_goes_where_pinyin_puts_it(base, tone, marked):
    assert render_syllable(base, tone) == marked


def test_a_phrase_is_space_separated():
    assert render(["yi", "bei", "shui"], ["4", "1", "3"]) == "yì bēi shuǐ"


def test_bad_input_is_refused():
    with pytest.raises(ValueError, match="unknown tone"):
        render_syllable("ma", "6")
    with pytest.raises(ValueError, match="no vowel"):
        render_syllable("ng", "2")
    with pytest.raises(ValueError, match="2 syllables but 3 tones"):
        render(["a", "b"], ["1", "2", "3"])
