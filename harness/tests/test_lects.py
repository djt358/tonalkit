"""contracts.lects: per-lect rules behind one small interface (only cmn so far)."""

import pytest

from tonekit_harness.contracts.lects import LectError, lect_rules


def test_cmn_rules_parse_and_apply_sandhi():
    rules = lect_rules("cmn")
    syllables = rules.parse_pinyin("shuǐ guǒ")
    assert [s.tone for s in syllables] == ["3", "3"]
    assert rules.surface_options(["3", "3"], ["shui", "guo"], "phrase") == {("2", "3")}


@pytest.mark.parametrize("grew_up_hearing,accent", [
    ("taiwan", "cmn-TW"), ("mainland", "cmn-standard"), ("singapore_malaysia", "cmn-standard"),
    ("hong_kong_macau", "cmn-standard"), ("other", "cmn-standard"), ("prefer_not", "cmn-standard"),
    (None, "cmn-standard"),
])
def test_cmn_default_accent(grew_up_hearing, accent):
    assert lect_rules("cmn").default_accent(grew_up_hearing) == accent


def test_an_unknown_lect_names_the_known_ones():
    with pytest.raises(LectError, match="no rules for lect 'yue'.*cmn"):
        lect_rules("yue")
