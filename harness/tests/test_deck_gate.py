"""deck_build.gate and gate_select: the gate pairs, chosen to cover the sandhi cases of 一."""

from collections import Counter

import pytest
from deck_support import SOURCES, gate_row

from tonekit_harness.deck_build import trial
from tonekit_harness.deck_build.errors import BuildError
from tonekit_harness.deck_build.gate import build_gate, standin_rows
from tonekit_harness.deck_build.gate_select import MAX_PER_MEASURE, quotas
from tonekit_harness.deck_build.lexicon import load_lexicon


@pytest.fixture(scope="module")
def lexicon():
    return load_lexicon(SOURCES / "tone_variants.csv")


@pytest.fixture(scope="module")
def standin():
    return standin_rows(SOURCES / "gate_standin.csv")


def test_the_standin_makes_twenty_pairs_the_contract_accepts(standin, lexicon):
    built = build_gate(standin, lexicon, 20)
    assert [c["id"] for c in built.cards] == [f"g{i:02d}-{k}" for i in range(1, 21) for k in "ce"]
    assert trial.problems(built.cards) == []  # pairs, one-tone errors, sandhi: the contract's own checks
    assert built.unusable == [] and built.passed_over == []


def test_the_pairs_cover_every_tone_after_yi_and_third_tone_runs(standin, lexicon):
    built = build_gate(standin, lexicon, 20)
    assert Counter(u.after_yi for u in built.selected) == {"1": 5, "2": 4, "3": 5, "4": 6}
    assert sum(u.has_t3_run for u in built.selected) >= 2
    assert max(Counter(u.measure for u in built.selected).values()) <= MAX_PER_MEASURE
    spoken_yi = Counter(c["produced_tones"][0] for c in built.cards if c["label"] == "correct")
    assert spoken_yi == {"4": 14, "2": 6}  # yì before 1, 2 and 3; yí before 4; never the citation yī


def test_a_third_tone_run_is_spoken_with_its_sandhi_and_the_error_is_in_the_measure_word(standin, lexicon):
    cards = {c["id"]: c for c in build_gate(standin, lexicon, 20).cards}
    assert (cards["g13-c"]["text"], cards["g13-c"]["pinyin"], cards["g13-c"]["produced_tones"]) == (
        "一碗水",
        "yì wán shuǐ",
        ["4", "2", "3"],
    )
    assert (cards["g13-e"]["text"], cards["g13-e"]["pinyin"], cards["g13-e"]["produced_tones"]) == (
        "一湾水",
        "yì wān shuǐ",
        ["4", "1", "3"],
    )
    assert cards["g13-e"]["intended"] == cards["g13-c"]["intended"]
    assert cards["g01-e"]["prompt_note"] == "Read it as written: 睡 as in 睡觉 (to sleep)."


def test_labels_are_toneless_syllables_and_the_pair_shares_its_intended_reading(standin, lexicon):
    for c in build_gate(standin, lexicon, 20).cards:
        assert c["intended"]["id"] == c["pair"]
        assert all(label.isalpha() and label.islower() for label in c["intended"]["labels"])
        assert c["status"] == "unverified"


def test_more_rows_than_pairs_are_chosen_from_in_file_order_and_the_rest_reported(standin, lexicon):
    built = build_gate(standin, lexicon, 10)
    texts = [u.reading.text for u in built.selected]
    assert len(texts) == 10 and texts == [r.reading.text for r in standin if r.reading.text in texts]
    assert len(built.passed_over) == 10 and all(x.reason.startswith("not needed") for x in built.passed_over)
    assert Counter(u.after_yi for u in built.selected) == quotas(10)


def test_quotas_always_add_up():
    assert quotas(20) == {"1": 5, "2": 4, "3": 5, "4": 6}
    for n in range(1, 41):
        assert sum(quotas(n).values()) == n


def test_too_few_usable_rows_is_an_error_with_the_whole_report(standin, lexicon):
    with pytest.raises(BuildError) as e:
        build_gate(standin, lexicon, 25)
    assert str(e.value).splitlines()[0] == "only 20 of 25 gate pairs can be made"


def test_rows_that_cannot_make_a_pair_are_reported_with_why(lexicon):
    rows = [
        gate_row("一杯水", "yī bēi shuǐ", "yī bēi shuǐ", where="g.csv:2"),  # citation tone where sandhi applies
        gate_row("两杯水", "liǎng bēi shuǐ", "liǎng bēi shuǐ", where="g.csv:3"),
        gate_row("一杯咖啡", "yī bēi kā fēi", "yì bēi kā fēi", where="g.csv:4"),  # 啡 is not in the lexicon
        gate_row("一杯茶水", "yī bēi chá", "yì bēi chá", where="g.csv:5"),  # 4 characters, 3 syllables
        gate_row("一本书", "yī běn shū", "yì běn shū", where="g.csv:6"),
        gate_row("一本书", "yī běn shū", "yì běn shū", where="g.csv:7"),
    ]
    with pytest.raises(BuildError) as e:
        build_gate(rows, lexicon, 5)
    lines = {line.split(" ")[4]: line for line in str(e.value).splitlines()[1:] if line.startswith("  can't use")}
    assert "is not a sandhi reading" in lines["g.csv:2"] and "1-1-3" in lines["g.csv:2"]
    assert "not a phrase that starts with the numeral 一" in lines["g.csv:3"]
    assert "啡 has no tone variant in the lexicon" in lines["g.csv:4"]
    assert "4 characters but 3 syllables" in lines["g.csv:5"]
    assert "the same phrase is in an earlier row" in lines["g.csv:7"]
    assert "g.csv:6" not in lines
