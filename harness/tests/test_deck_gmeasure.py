"""deck_build.gmeasure: DJ's g_measure table as the source of gate phrases (a synthetic table here;
the real file never enters the repository)."""

import pytest
from deck_support import SOURCES

from tonekit_harness.deck_build import trial
from tonekit_harness.deck_build.errors import BuildError
from tonekit_harness.deck_build.gate import build_gate
from tonekit_harness.deck_build.gmeasure import read_gmeasure, resolve_columns
from tonekit_harness.deck_build.lexicon import load_lexicon

# a table shaped like the g_measure draft: the phrase is word + measure, the pinyin columns are DJ's
COMPOSED = """\
tile_id,word,measure,weight,referent,register,citation_pinyin,spoken_pinyin,dj_status
t01,水,杯,1,x,neutral,yī bēi shuǐ,yì bēi shuǐ,unverified
t02,书,本,1,x,neutral,yī běn shū,yì běn shū,unverified
t03,鱼,条,1,x,neutral,yī tiáo yú,yì tiáo yú,unverified
t04,饭,碗,1,x,neutral,yī wǎn fàn,yì wǎn fàn,unverified
t05,车,辆,1,x,neutral,yī liàng chē,yí liàng chē,unverified
t06,纸,张,1,x,neutral,yī zhāng zhǐ,yī zhāng zhǐ,unverified
t07,咖啡,杯,1,x,neutral,yī bēi kā fēi,yì bēi kā fēi,unverified
t08,,杯,1,x,neutral,yī bēi,yì bēi,unverified
t09,花,束,1,x,neutral,,,unverified
"""

PHRASE = """\
id,cn,trad,py_cit,py_spoken
1,一杯水,一杯水,yī bēi shuǐ,yì bēi shuǐ
2,三杯水,三杯水,sān bēi shuǐ,sān bēi shuǐ
"""


@pytest.fixture(scope="module")
def lexicon():
    return load_lexicon(SOURCES / "tone_variants.csv")


def table(tmp_path, text, name="g_measure.csv"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_the_phrase_is_put_together_from_measure_and_word_and_other_columns_are_ignored(tmp_path):
    rows, left = read_gmeasure(table(tmp_path, COMPOSED))
    assert [r.reading.text for r in rows] == [
        "一杯水",
        "一本书",
        "一条鱼",
        "一碗饭",
        "一辆车",
        "一张纸",
        "一杯咖啡",
    ]
    assert rows[0].reading.citation_pinyin == "yī bēi shuǐ" and rows[0].reading.spoken_pinyin == "yì bēi shuǐ"
    assert [(x.where, x.text) for x in left] == [("g_measure.csv:9", ""), ("g_measure.csv:10", "一束花")]
    assert left[0].reason.startswith("no phrase") and left[1].reason == "citation_pinyin or spoken_pinyin is empty"


def test_a_table_of_phrases_with_other_column_names_is_mapped_by_hand(tmp_path):
    path = table(tmp_path, PHRASE)
    with pytest.raises(BuildError, match=r"no column for citation_pinyin, spoken_pinyin, text.*--gmeasure-map"):
        read_gmeasure(path)
    mapping = {"text": "cn", "text_traditional": "trad", "citation_pinyin": "py_cit", "spoken_pinyin": "py_spoken"}
    rows, left = read_gmeasure(path, mapping)
    assert left == [] and rows[0].reading.text_traditional == "一杯水"
    assert [r.reading.text for r in rows] == ["一杯水", "三杯水"]


def test_a_mapping_that_names_nothing_is_refused():
    with pytest.raises(BuildError, match="unknown field 'phrase'"):
        resolve_columns(["a"], {"phrase": "a"})
    with pytest.raises(BuildError, match="no column 'zz' for text"):
        resolve_columns(["a"], {"text": "zz"})


def test_an_empty_table_is_an_error(tmp_path):
    with pytest.raises(BuildError, match="no rows"):
        read_gmeasure(table(tmp_path, "word,measure\n"))


def test_pairs_are_chosen_from_the_table_and_every_row_left_out_says_why(tmp_path, lexicon):
    rows, no_phrase = read_gmeasure(table(tmp_path, COMPOSED))
    built = build_gate(rows, lexicon, 3, earlier_unusable=no_phrase)
    assert [u.reading.text for u in built.selected] == ["一杯水", "一本书", "一辆车"]  # yì before 1 and 3, yí before 4
    assert trial.problems(built.cards) == []
    assert not any(f.startswith("stand-in") for f in built.flags.values())
    reasons = {x.text: x.reason for x in built.unusable + built.passed_over}
    assert reasons["一张纸"].startswith("its own pinyin does not hold") and "1-1-3" in reasons["一张纸"]
    assert "啡 has no tone variant" in reasons["一杯咖啡"]
    assert reasons["一束花"] == "citation_pinyin or spoken_pinyin is empty"
    assert reasons["一条鱼"].startswith("not needed") and reasons["一碗饭"].startswith("not needed")


def test_a_numeral_column_is_used_and_pinyin_written_in_words_is_spaced(tmp_path):
    path = table(
        tmp_path,
        "numeral,measure,word,citation_pinyin,spoken_pinyin\n"
        "一,杯,咖啡,yī bēi kāfēi,yì bēi kāfēi\n两,杯,水,liǎng bēi shuǐ,liǎng bēi shuǐ\n",
    )
    rows, left = read_gmeasure(path)
    assert left == [] and [r.reading.text for r in rows] == ["一杯咖啡", "两杯水"]
    assert rows[0].reading.citation_pinyin == "yī bēi kā fēi" and rows[0].reading.spoken_pinyin == "yì bēi kā fēi"
    with pytest.raises(BuildError) as e:  # 一杯咖啡 has no error word in the lexicon, 两杯水 is not a 一 phrase
        build_gate(rows, load_lexicon(SOURCES / "tone_variants.csv"), 1)
    assert "can't use g_measure.csv:3 两杯水: not a phrase that starts with the numeral 一" in str(e.value)
