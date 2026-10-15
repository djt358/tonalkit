"""Ruling R122: reading a public corpus's transcript into produced tones with C0's sandhi checker,
and dropping what the transcript does not settle."""

from __future__ import annotations

import pytest

from tonekit_harness.adapt import drops
from tonekit_harness.adapt.reading import Dropped, Reading, Transcript, read


def transcript(hanzi: str, pinyin: str, *, words: str | None = None, per_recording: bool = True) -> Transcript:
    """`words` writes the word boundaries as spaces between the hanzi, as THCHS-30's first line."""
    word_of = None
    if words is not None:
        word_of = tuple(i for i, word in enumerate(words.split()) for _ in word)
        assert "".join(words.split()) == hanzi
    return Transcript(tuple(hanzi), tuple(pinyin.split()), word_of, per_recording)


def tones(t: Transcript) -> str:
    r = read(t)
    assert isinstance(r, Reading), r
    return "-".join(r.tones)


def reason(t: Transcript) -> str:
    r = read(t)
    assert isinstance(r, Dropped), r
    return r.reason


# ---- spoken (surface) transcripts --------------------------------------------------------------


@pytest.mark.parametrize("per_recording", [True, False])
def test_a_transcript_written_as_spoken_is_taken_as_it_stands(per_recording):
    t = transcript("一个人不是", "yi2 ge4 ren2 bu2 shi4", per_recording=per_recording)
    r = read(t)
    assert isinstance(r, Reading)
    assert (r.tones, r.bases, r.form) == (("2", "4", "2", "2", "4"), ("yi", "ge", "ren", "bu", "shi"), "surface")


def test_third_tone_sandhi_written_as_spoken_is_kept():
    assert tones(transcript("你好", "ni2 hao3")) == "2-3"
    assert read(transcript("你好", "ni2 hao3")).form == "either"  # 2-3 is also a citation


@pytest.mark.parametrize("hanzi,pinyin", [("我的", "wo3 de5"), ("第一次", "di4 yi1 ci4"), ("统一", "tong3 yi1")])
def test_tones_no_sandhi_touches_are_kept(hanzi, pinyin):
    assert tones(transcript(hanzi, pinyin)) == "-".join(p[-1] for p in pinyin.split())


def test_a_spoken_reading_no_citation_explains_is_dropped():
    # 一 before a first tone is yì, never yí
    assert reason(transcript("一天", "yi2 tian1")) == drops.INCONSISTENT


@pytest.mark.parametrize("pinyin", ["zhan2 lan2 guan3", "zhan3 lan2 guan3"])
def test_a_spoken_reading_of_a_run_with_two_native_readings_is_dropped(pinyin):
    # 展览馆 is 2-2-3 or 3-2-3 (R89): either spelling could stand for the other reading
    assert reason(transcript("展览馆", pinyin)) == drops.MANY_READINGS


# ---- citation transcripts ----------------------------------------------------------------------


def test_a_per_recording_transcript_with_dictionary_tones_is_dropped():
    assert reason(transcript("你好", "ni3 hao3")) == drops.THIRD_TONES
    assert reason(transcript("一天", "yi1 tian1")) == drops.YI_BU_DICTIONARY
    assert reason(transcript("不对", "bu4 dui4")) == drops.YI_BU_DICTIONARY


def test_a_script_transcript_with_dictionary_tones_goes_through_the_checker():
    t = transcript("不对你好", "bu4 dui4 ni3 hao3", words="不对 你好", per_recording=False)
    r = read(t)
    assert isinstance(r, Reading) and (r.tones, r.form) == (("2", "4", "2", "3"), "citation")


def test_a_script_transcripts_third_tone_sandhi_counts_inside_a_word_only():
    inside = transcript("可以去", "ke3 yi3 qu4", words="可以 去", per_recording=False)
    assert tones(inside) == "2-3-4"
    across = transcript("我想去", "wo3 xiang3 qu4", words="我 想 去", per_recording=False)
    assert reason(across) == drops.T3_ACROSS_WORDS  # a pause between the words blocks the sandhi
    unknown = transcript("可以去", "ke3 yi3 qu4", per_recording=False)
    assert reason(unknown) == drops.T3_ACROSS_WORDS


def test_a_spoken_three_two_three_is_dropped_since_the_two_may_be_a_sandhid_three():
    # 我很好 (citation 3-3-3) is said 2-2-3 or 3-2-3; 我没有 is a true 3-2-3, but the text cannot say
    assert reason(transcript("我很好", "wo3 hen2 hao3")) == drops.MANY_READINGS


def test_a_script_transcripts_one_in_its_dictionary_tone_is_dropped():
    # 一月 is yī yuè, 一个 yí gè: the checker cannot tell a date from a count
    assert reason(transcript("一月", "yi1 yue4", words="一月", per_recording=False)) == drops.YI_BU_DICTIONARY


def test_a_script_transcript_with_two_native_readings_is_dropped():
    t = transcript("展览馆", "zhan3 lan3 guan3", words="展览馆", per_recording=False)
    assert reason(t) == drops.MANY_READINGS


def test_dictionary_and_sandhi_tones_in_one_transcript_are_dropped():
    t = transcript("不是我老爹", "bu2 shi4 wo3 lao3 die1", per_recording=False)
    assert reason(t) == drops.MIXED


# ---- what no transcript settles ----------------------------------------------------------------


@pytest.mark.parametrize("hanzi,pinyin", [("一下", "yi1 xia5"), ("一下", "yi2 xia5"), ("不了", "bu4 le5")])
def test_one_or_bu_before_a_neutral_syllable_is_dropped(hanzi, pinyin):
    assert reason(transcript(hanzi, pinyin)) == drops.NEUTRAL_YI_BU


@pytest.mark.parametrize(
    "hanzi,pinyin", [("想想", "xiang3 xiang5"), ("想想", "xiang2 xiang5"), ("姐姐", "jie3 jie5")]
)
def test_a_reduplication_into_the_neutral_tone_after_a_low_tone_is_dropped(hanzi, pinyin):
    assert reason(transcript(hanzi, pinyin)) == drops.NEUTRAL_REDUPLICATION


def test_a_reduplication_after_a_first_or_fourth_tone_is_kept():
    assert tones(transcript("妈妈", "ma1 ma5")) == "1-5"
    assert tones(transcript("看看", "kan4 kan5")) == "4-5"


@pytest.mark.parametrize(
    "hanzi,pinyin", [("哪儿", "na3 er5"), ("哪儿", "na3 r5"), ("花儿", "huar1 er5"), ("花", "hua1r")]
)
def test_erhua_is_dropped(hanzi, pinyin):
    assert reason(transcript(hanzi, pinyin)) == drops.ERHUA


def test_er_as_a_full_syllable_is_kept():
    assert tones(transcript("女儿", "nv3 er2")) == "3-2"


@pytest.mark.parametrize(
    "hanzi,pinyin,why",
    [
        ("A好", "ei1 hao3", drops.NON_MANDARIN),
        ("你好", "ni2 xyz3", drops.NON_MANDARIN),
        ("你好", "ni2 hao", drops.NO_TONE),
        ("你好", "ni2", drops.MALFORMED),
        ("", "", drops.MALFORMED),
    ],
)
def test_tokens_that_are_not_mandarin_syllables_are_dropped(hanzi, pinyin, why):
    assert reason(transcript(hanzi, pinyin)) == why


def test_word_boundaries_must_cover_the_syllables():
    t = Transcript(("你", "好"), ("ni2", "hao3"), (0,), True)
    assert reason(t) == drops.MALFORMED
