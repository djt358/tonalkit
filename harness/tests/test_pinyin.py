"""contracts.pinyin: tone-marked and numbered pinyin into syllables and cmn tone ids."""

import unicodedata

import pytest

from tonekit_harness.contracts.pinyin import PinyinError, Syllable, parse_pinyin, tones_of


def pairs(text: str) -> list[tuple[str, str]]:
    return [(s.base, s.tone) for s in parse_pinyin(text)]


def test_tone_marked_phrase():
    assert pairs("yì bēi shuǐ") == [("yi", "4"), ("bei", "1"), ("shui", "3")]


def test_numbered_phrase():
    assert pairs("yi4 bei1 shui3") == [("yi", "4"), ("bei", "1"), ("shui", "3")]


def test_a_syllable_keeps_the_text_it_was_written_as():
    assert parse_pinyin("shuǐ shui3")[0] == Syllable(text="shuǐ", base="shui", tone="3")
    assert parse_pinyin("shuǐ shui3")[1].text == "shui3"


@pytest.mark.parametrize("vowel,tones", [
    ("ā á ǎ à", "1234"), ("ē é ě è", "1234"), ("ī í ǐ ì", "1234"),
    ("ō ó ǒ ò", "1234"), ("ū ú ǔ ù", "1234"), ("ǖ ǘ ǚ ǜ", "1234"),
])
def test_every_vowel_takes_each_of_the_four_marks(vowel, tones):
    marked = vowel.split()
    assert [s.tone for s in parse_pinyin(" ".join("l" + m for m in marked))] == list(tones)


def test_no_mark_is_the_neutral_tone():
    assert tones_of("zhè ge") == ["4", "5"]
    assert tones_of("ma") == ["5"]


def test_numbered_neutral_is_five():
    assert tones_of("ma5") == ["5"]


@pytest.mark.parametrize("written,base,tone", [
    ("lǜ", "lü", "4"), ("lv4", "lü", "4"), ("nǚ", "nü", "3"), ("nv3", "nü", "3"),
    ("lüè", "lüe", "4"), ("lüe4", "lüe", "4"), ("nü", "nü", "5"),
])
def test_u_umlaut_and_v_are_the_same_vowel(written, base, tone):
    assert pairs(written) == [(base, tone)]


def test_composed_and_decomposed_unicode_agree():
    assert parse_pinyin(unicodedata.normalize("NFD", "lǚ guǎn"))[0].base == "lü"
    assert tones_of(unicodedata.normalize("NFD", "lǚ guǎn")) == ["3", "3"]
    assert tones_of(unicodedata.normalize("NFC", "lǚ guǎn")) == ["3", "3"]


def test_capitals_and_extra_whitespace_are_fine():
    assert pairs("  Běi   jīng\t") == [("bei", "3"), ("jing", "1")]


def test_an_apostrophe_separates_syllables():
    assert pairs("xī'ān") == [("xi", "1"), ("an", "1")]


@pytest.mark.parametrize("written,base", [
    ("huār", "huar"), ("èr", "er"), ("yuán", "yuan"), ("jūn", "jun"), ("xiōng", "xiong"),
    ("zhī", "zhi"), ("wēng", "weng"), ("yòng", "yong"), ("duì", "dui"),
])
def test_real_syllables_parse(written, base):
    assert [s.base for s in parse_pinyin(written)] == [base]


@pytest.mark.parametrize("bad", ["shuuǐ", "xyz", "bcd", "yìbēishuǐ", "shui33"])
def test_not_a_syllable_names_the_syllable(bad):
    with pytest.raises(PinyinError) as e:
        parse_pinyin(f"yì bēi {bad}")
    assert repr(bad) in str(e.value)


def test_two_tone_marks_in_one_syllable():
    with pytest.raises(PinyinError, match="'shǔǐ'.*more than one tone"):
        parse_pinyin("yì shǔǐ")


def test_a_mark_and_a_digit_in_one_syllable():
    with pytest.raises(PinyinError, match="'shuǐ3'.*both"):
        parse_pinyin("shuǐ3")


@pytest.mark.parametrize("digit", ["0", "6", "9"])
def test_a_digit_outside_one_to_five(digit):
    with pytest.raises(PinyinError, match=f"'shui{digit}'"):
        parse_pinyin(f"shui{digit}")


def test_a_digit_must_end_the_syllable():
    with pytest.raises(PinyinError, match="'sh3ui'"):
        parse_pinyin("sh3ui")


def test_a_tone_mark_on_a_consonant():
    with pytest.raises(PinyinError, match="'sh́ui'.*vowel"):
        parse_pinyin("sh́ui")


@pytest.mark.parametrize("bad", ["水guǒ", "shui!", "shuǐ,"])
def test_stray_characters_name_the_syllable(bad):
    with pytest.raises(PinyinError) as e:
        parse_pinyin(bad)
    assert repr(bad) in str(e.value)


@pytest.mark.parametrize("empty", ["", "   ", "'"])
def test_empty_pinyin_is_an_error(empty):
    with pytest.raises(PinyinError, match="no syllables"):
        parse_pinyin(empty)


def test_the_error_quotes_the_whole_text_for_context():
    with pytest.raises(PinyinError, match="in 'yì bēi shuuǐ'"):
        parse_pinyin("yì bēi shuuǐ")
