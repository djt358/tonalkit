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
        "no_sound", "finish_early", "finish_early_confirm",
    ],
    "pause": ["title", "body", "resume"],
    "done": ["title", "body", "code_label", "code_note", "delete", "delete_confirm", "delete_confirm_unsent", "deleted"],
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
        assert value, f"{key} is empty"
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
    assert "We keep what you already sent" in confirm and "send us your code" in confirm
    assert "\n" not in confirm  # it is the text of a native confirm() box


def test_deleting_before_sending_says_nothing_has_been_sent():
    # R90: the confirm before any share. Nobody should read "we keep what you sent" when nothing was.
    unsent = copy()["done.delete_confirm_unsent"]
    assert unsent == "Nothing has been sent to us yet. Deleting removes your recordings from this phone for good."
    assert "\n" not in unsent  # it is the text of a native confirm() box
    assert "keep" not in unsent and "send us your code" not in unsent


def test_the_done_screen_does_not_claim_every_card_was_read():
    # "Finish and send what I have" reaches this screen with cards left, so it can't say "every card".
    body = copy()["done.body"]
    assert body.startswith("You're done with the cards. Tap Share to send your recordings.")
    assert "every card" not in body.lower()


def test_the_phrase_hint_asks_for_one_phrase_not_one_character_at_a_time():
    # A reader going one character at a time says the base tone of 一 and 不 and misses the sandhi.
    assert copy()["card.phrase_hint"] == "Say it as one phrase, at your normal pace."


def test_a_quiet_microphone_check_says_how_far_to_hold_the_phone():
    values = copy()
    assert values["mic.level_low"] == "A bit quiet. Hold the phone about a hand's width from your mouth."
    assert "hand's width" in values["mic.body"] and len(values["mic.body"]) < 200  # one short line, no more


def test_a_take_with_no_sound_is_not_kept_and_the_volunteer_is_told_what_to_do():
    # The kit refuses a silent take (kit/app/silence.js): the card stays unrecorded.
    assert copy()["card.no_sound"] == (
        "We didn't hear anything. Please record it again. If it keeps happening, reload the page."
    )


APPS = ["WeChat", "RedNote", "Douyin", "TikTok", "LinkedIn", "Snapchat", "Weibo", "QQ", "Instagram", "Facebook", "Line"]


def test_every_way_to_stop_before_consent_says_how_to_open_safari_in_both_languages():
    values = copy()
    for key in ("error.in_app_browser", "error.unsupported"):
        assert "Open in Safari (在Safari中打开)." in values[key], key  # the label Chinese-language WeChat shows
        assert not [app for app in APPS if app in values[key]], key  # R92: the stop screen works for any app


def test_the_microphone_help_names_the_settings_path_and_no_glyph():
    blocked = copy()["error.mic_blocked"]
    assert "Open Settings, tap Apps, then Safari, then Microphone, and choose Allow." in blocked
    assert "aA" not in blocked


@pytest.mark.parametrize("word", JARGON)
def test_nothing_a_volunteer_reads_is_jargon(word):
    assert not re.search(rf"\b{re.escape(word)}", volunteer_text().lower())
