"""kit/CONSENT.md and kit/GUIDE.md: the shape the kit's tiny markdown renderer and DJ's audit rely on,
and the lengths the brief set. The wording is DJ's to audit; these checks stop it drifting in form."""

import re

from kit_support import CONSENT, GUIDE, copy, text

VERSION_LINE = "<!-- consent: v1 -->"
SECTIONS = ["What DJ records", "Why", "Who gets it", "What DJ will never do", "How long DJ keeps it", "Your choice"]
MAX_CONSENT_WORDS = 330  # R72 and R78 need the words; every word still has to earn its place
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
    assert text(CONSENT).split("\n", 1)[0] == VERSION_LINE


def test_the_consent_fits_in_330_words():
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


def test_the_guide_has_a_place_for_the_link_and_a_sign_off():
    lines = text(GUIDE).strip().splitlines()
    assert "[paste the link here]" in lines
    assert lines[-1] == "DJ"


def test_the_consent_says_what_dj_decided_about_use_place_and_deletion():
    consent = body()
    assert "test the checker on real voices and tune its settings" in consent  # R72: testing and tuning
    assert "DJ may publish overall results and the tuned settings, never your recordings." in consent
    assert (  # R78: who can open the workspace comes before what DJ does in it
        "in a private cloud workspace that only DJ's account can open, where DJ uses an AI assistant "
        "(Anthropic's Claude)."
    ) in consent
    assert "The private workspace above is the one exception." in consent
    assert "(characters or pinyin, simplified or traditional)" in consent  # R74
    assert "redoes anything not yet released without you" in consent  # R72
    assert "Results and settings already released can't be pulled back, but they contain no audio." in consent


def test_the_consent_says_dj_every_time_and_never_we_us_or_i():
    consent = body().replace(f"**{copy()['consent.agree']}**", "")  # the button's own words are the reader's
    assert not re.search(r"\b(we|us|our|i|me|my)\b", consent, re.I), "DJ is named every time, never 'we' or 'I'"
    assert "Nobody" not in consent
