"""kit/CONSENT.md and kit/GUIDE.md: the shape the kit's tiny markdown renderer and DJ's audit rely on,
and the lengths the brief set. The wording is DJ's to audit; these checks stop it drifting in form."""

import re

from kit_support import CONSENT, GUIDE, copy, text

VERSION_LINE = re.compile(r"<!-- consent: v\d+(?:\.\d+)* -->")
SECTIONS = ["What we record", "Why", "Who gets it", "What will never happen", "How long we keep it", "Your choice"]
MAX_CONSENT_WORDS = 350  # every word still has to earn its place
MAX_GUIDE_WORDS = 250

HEADING = re.compile(r"## \S.*")
BULLET = re.compile(r"- \S.*")


def spoken_words(markdown: str) -> int:
    """Words a reader reads: list and heading marks and bold markers don't count."""
    plain = re.sub(r"^(#+|-)\s+", "", markdown, flags=re.M).replace("**", "")
    return len(plain.split())


def body() -> str:
    return text(CONSENT).split("\n", 1)[1]


def test_the_first_line_is_the_version_the_kit_reads():
    assert VERSION_LINE.fullmatch(text(CONSENT).split("\n", 1)[0])


def test_the_consent_fits_in_350_words():
    assert spoken_words(body()) <= MAX_CONSENT_WORDS


def test_the_consent_uses_only_headings_paragraphs_bullets_and_bold():
    for line in body().splitlines():
        if not line.strip():
            continue
        if line.startswith("#"):
            assert HEADING.fullmatch(line), f"only second-level headings: {line!r}"
        elif line.startswith("-"):
            assert BULLET.fullmatch(line), line
        assert not re.match(r"\s|\d+[.)]\s|>|\|", line), f"no indents, numbered lists, quotes or tables: {line!r}"
        assert not re.search(r"`|\[[^\]]*\]\(|(?<!\*)\*(?!\*)|_|<", line), f"no code, links, italics or html: {line!r}"
        assert line.count("**") % 2 == 0, line


def test_the_consent_covers_what_the_brief_requires_in_order():
    headings = [line.removeprefix("## ") for line in body().splitlines() if line.startswith("## ")]
    assert headings == SECTIONS


def test_the_consent_ends_on_the_agree_button_the_kit_shows():
    last = body().strip().splitlines()[-1]
    assert f"**{copy()['consent.agree']}**" in last


def test_the_guide_fits_in_250_words_and_is_plain_text_for_a_message():
    guide = text(GUIDE)
    assert spoken_words(guide) <= MAX_GUIDE_WORDS
    assert not re.search(r"^#|\*\*|`|\]\(", guide, re.M), "the guide is pasted into a text message: no markdown"


def test_the_guide_has_the_link_and_a_sign_off():
    lines = text(GUIDE).strip().splitlines()
    assert any(re.fullmatch(r"https://\S+", line) for line in lines)
    assert lines[-1] == "DJ"


def test_the_consent_says_what_was_decided_about_use_place_and_deletion():
    consent = body()
    assert "test the checker on real voices and tune its settings" in consent  # R72: testing and tuning
    assert "We may publish overall results and the tuned settings, but we will never release your recordings." in consent
    assert "in a private cloud workspace that only the team can open." in consent  # R78: where it is analysed
    assert "(characters or pinyin, simplified or traditional)" in consent  # R74
    assert "can't be pulled back if they're already released, but they contain no audio or identifying data." in consent


def test_volunteer_facing_text_names_no_one():
    """The consent and the kit's copy speak for the project ("we", "the team"), never one person: a
    promise that names one person reads as if anyone else could break it. The guide is the
    organiser's own message, signed by them, so it may say "I"."""
    assert not re.search(r"\bDJ\b", body())
    assert not [k for k, v in copy().items() if re.search(r"\bDJ\b", v)]
