"""kit/copy.json: the strings the kit shows. The keys are the contract with the kit (docs/s05/plan.md,
P1 and P4), the option labels follow the session enums in docs/s05/contracts.md section 2, and the
words are plain: nothing a volunteer would have to ask about."""

import re

import pytest
from kit_support import copy, volunteer_text

SCREENS = {
    "welcome": ["title", "body", "start"],
    "consent": ["title", "agree", "decline"],
    "background": ["title", "intro", "next"],
    "mic": ["title", "body", "allow", "checking", "level_ok", "level_low", "noisy", "continue"],
    "card": [
        "progress", "record", "stop", "play", "redo", "skip", "next", "note", "isolated_hint", "phrase_hint", "saved",
    ],
    "pause": ["title", "body", "resume"],
    "done": ["title", "body", "code_label", "code_note"],
    "share": ["button", "fallback", "done"],
    "error": ["mic_blocked", "unsupported", "storage", "generic"],
}  # fmt: skip

# The session enums (contracts section 2). `reading` values use "+" in the bundle and "_" in keys.
ENUMS = {
    "background": ["native", "heritage", "learner", "prefer_not"],
    "grew_up_hearing": ["mainland", "taiwan", "singapore_malaysia", "hong_kong_macau", "other", "prefer_not"],
    "reading": ["hanzi", "hanzi_pinyin"],
}


def expected_keys() -> set[str]:
    screens = {f"{screen}.{name}" for screen, names in SCREENS.items() for name in names}
    questions = {f"background.{field}.{value}" for field, values in ENUMS.items() for value in values}
    labels = {f"background.{field}.label" for field in ENUMS}
    return screens | questions | labels


# Words that would send a volunteer to a search engine, or into the project's insides.
JARGON = [
    "f0", "pitch track", "gate", "corpus", "manifest", "sandhi", "wav", "khz", "16 k", "sample rate", "bundle",
    "session.json", "tkh", "calibrat", "embedding", "classifier", "threshold", "algorithm",
]  # fmt: skip


def test_the_keys_are_exactly_the_contract():
    assert set(copy()) == expected_keys()


def test_every_value_is_a_plain_one_line_string():
    for key, value in copy().items():
        assert isinstance(value, str) and value.strip() == value and value, key
        assert "\n" not in value, key


def test_only_the_documented_placeholders_appear():
    placeholders = {key: set(re.findall(r"\{(\w+)\}", value)) for key, value in copy().items()}
    assert placeholders.pop("card.progress") == {"n", "total"}
    assert placeholders.pop("card.note") == {"note"}
    assert copy()["card.note"] == "{note}"  # the deck's prompt_note carries its own wording
    assert {key: found for key, found in placeholders.items() if found} == {}


@pytest.mark.parametrize("field", ENUMS)
def test_each_question_offers_every_enum_value_and_nothing_else(field):
    offered = {
        key.split(".")[2] for key in copy() if key.startswith(f"background.{field}.") and not key.endswith(".label")
    }
    assert offered == set(ENUMS[field])


def test_prefer_not_to_say_reads_the_same_on_both_questions():
    values = copy()
    assert values["background.background.prefer_not"] == values["background.grew_up_hearing.prefer_not"]
    assert values["background.background.prefer_not"] == "Prefer not to say"


def test_the_reading_question_has_no_way_to_decline():
    # `reading` is how the cards are shown, so the bundle enum has no prefer_not (contracts section 2).
    assert not any(key.startswith("background.reading.prefer") for key in copy())


@pytest.mark.parametrize("word", JARGON)
def test_nothing_a_volunteer_reads_is_jargon(word):
    assert not re.search(rf"\b{re.escape(word)}", volunteer_text().lower())
