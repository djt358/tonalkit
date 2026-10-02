"""kit/copy.json: the strings the kit shows. The keys are the contract with the kit (docs/s05/plan.md,
P1 and P4), the option labels follow the session enums in docs/s05/contracts.md section 2, and the
words are plain: nothing a volunteer would have to ask about."""

import re

import pytest
from kit_support import copy, volunteer_text

SCREENS = {
    "welcome": ["title", "body", "start"],
    "consent": ["title", "agree", "decline", "declined"],
    "background": ["title", "intro", "next"],
    "mic": ["title", "body", "allow", "checking", "level_ok", "level_low", "noisy", "continue"],
    "card": [
        "progress", "record", "stop", "play", "redo", "skip", "next", "note", "isolated_hint", "phrase_hint", "saved",
        "finish_early", "finish_early_confirm",
    ],
    "pause": ["title", "body", "resume"],
    "done": ["title", "body", "code_label", "code_note", "delete", "delete_confirm", "deleted"],
    "share": ["button", "again", "fallback", "done"],
    "error": ["mic_blocked", "unsupported", "in_app_browser", "storage", "generic"],
}  # fmt: skip

# The session enums (contracts section 2). `reading` values use "+" in the bundle and "_" in keys.
ENUMS = {
    "background": ["native", "heritage", "learner", "prefer_not"],
    "grew_up_hearing": ["mainland", "taiwan", "singapore_malaysia", "hong_kong_macau", "other", "prefer_not"],
    "reading": ["hanzi", "hanzi_pinyin"],
    "script": ["simplified", "traditional"],  # R74
}
BLANK_ALLOWED = {"card.phrase_hint"}  # a card with nothing to add shows no hint (the kit hides an empty one)
NO_DECLINE = ["reading", "script"]  # how the cards look, so the bundle enums have no prefer_not


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
        assert isinstance(value, str) and value.strip() == value, key
        assert value or key in BLANK_ALLOWED, f"{key} is empty"
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


@pytest.mark.parametrize("field", NO_DECLINE)
def test_the_questions_about_how_the_cards_look_have_no_way_to_decline(field):
    # They are display settings, so their bundle enums have no prefer_not (contracts section 2).
    assert not any(key.startswith(f"background.{field}.prefer") for key in copy())


def test_the_script_question_shows_each_script_in_its_own_characters():
    values = copy()
    assert values["background.script.label"] == "Which characters do you read more easily?"
    assert values["background.script.simplified"] == "Simplified (简体)"
    assert values["background.script.traditional"] == "Traditional (繁體)"


def test_the_intro_says_which_questions_can_be_declined_and_gives_no_count():
    intro = copy()["background.intro"]
    assert "Prefer not to say on the first two" in intro
    assert not re.search(r"\b(two|three|four|2|3|4) (quick )?questions", intro, re.I)


def test_the_heritage_option_describes_a_childhood_not_an_ability():
    heritage = copy()["background.background.heritage"]
    assert heritage.startswith("Heritage speaker: I grew up with Mandarin at home")
    assert not re.search(r"strongest|fluent|not very|broken|bad", heritage, re.I)


def test_deleting_from_the_phone_says_it_cannot_be_undone_and_what_dj_keeps():
    confirm = copy()["done.delete_confirm"]
    assert "can't be undone" in confirm
    assert "DJ keeps what you already sent" in confirm and "send DJ your code" in confirm
    assert "\n" not in confirm  # it is the text of a native confirm() box


def test_every_way_to_stop_before_consent_says_how_to_open_safari():
    values = copy()
    for key in ("error.in_app_browser", "error.unsupported"):
        assert "Open in Safari" in values[key], key
    assert "WeChat" not in values["error.in_app_browser"]  # the screen names no app; it works for any of them


def test_the_microphone_help_names_the_settings_path_and_no_glyph():
    blocked = copy()["error.mic_blocked"]
    assert "Open Settings, tap Apps, then Safari, then Microphone, and choose Allow." in blocked
    assert "aA" not in blocked


@pytest.mark.parametrize("word", JARGON)
def test_nothing_a_volunteer_reads_is_jargon(word):
    assert not re.search(rf"\b{re.escape(word)}", volunteer_text().lower())
