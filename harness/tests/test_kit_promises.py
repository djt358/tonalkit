"""kit/PROMISES.md keeps the promises honest: every quotation is word for word in the file it names, every
"never" in the consent has a row, every mechanism has a status, and the files it points at exist. The
checks that are buildable now live beside it: the volunteer register row and sign-offs in
test_kit_register.py, the no-network-client scan in test_kit_network.py."""

import re

from kit_support import CONSENT, GUIDE, KIT, PROMISES, REPO, copy, text

HEADER = ["Promise", "Where we say it", "Mechanism that keeps it", "Test"]
QUOTED = re.compile(r'(CONSENT|GUIDE|copy [\w.]+) "([^"]+)"')
STATUS = re.compile(r"\(built(?:, as policy)?\)|\b(?:P4|P5|C0|E1) \(built\)|\b(?:P4|P5) \(pending\)|OP \(operational\)")

# Files a task built on its own branch arrive with its merge. Until then they are not here to check:
# a path (or test name) is exempt only while the marker that its branch is merged is missing.
ARRIVES_WITH = {
    "kit/app/": "kit/app",
    "kit/tests/": "kit/app",
    "test_bundle.py": "harness/src/tonekit_harness/contracts/wav_check.py",  # C0 only
    "test_registry_refusals.py": "harness/src/tonekit_harness/registry",
    "test_registry_stale.py": "harness/src/tonekit_harness/registry",
}


def table() -> list[list[str]]:
    lines = [line for line in text(PROMISES).splitlines() if line.startswith("|")]
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    assert rows[0] == HEADER
    assert set(rows[1][0]) <= set("- ")  # the separator row
    return rows[2:]


def source_text(source: str) -> str:
    if source == "CONSENT":
        return text(CONSENT)
    if source == "GUIDE":
        return text(GUIDE)
    return copy()[source.removeprefix("copy ")]


def quotations() -> list[tuple[str, str]]:
    return [(source, quote) for row in table() for source, quote in QUOTED.findall(row[1])]


def never_bullets() -> list[str]:
    section = text(CONSENT).split("## What will never happen\n", 1)[1].split("\n## ", 1)[0]
    return [line.removeprefix("- ") for line in section.splitlines() if line.startswith("- ")]


def not_here_yet(name: str) -> bool:
    """True for a file that arrives with a branch that isn't merged here yet."""
    return any(name.startswith(key) and not (REPO / marker).exists() for key, marker in ARRIVES_WITH.items())


def test_every_row_has_all_four_cells_filled_in():
    rows = table()
    assert len(rows) >= 10
    for row in rows:
        assert len(row) == len(HEADER) and all(row), row


def test_every_quotation_is_word_for_word_in_the_file_it_names():
    for source, quote in quotations():
        assert quote in source_text(source), f"{source}: {quote!r}"


def test_every_row_quotes_what_it_promises():
    for row in table():
        assert QUOTED.search(row[1]), f"no quotation in: {row[0]}"


def test_every_never_in_the_consent_has_a_row():
    quoted = {quote for _, quote in quotations()}
    for bullet in never_bullets():
        assert bullet in quoted, bullet
    assert len(never_bullets()) == 4


def test_every_mechanism_and_every_test_says_whether_it_is_built():
    for promise, _, mechanism, test in table():
        assert STATUS.search(mechanism), f"mechanism has no status: {promise}"
        assert STATUS.search(test) or test.startswith("None"), f"test has no status: {promise}"


def test_the_files_the_register_points_at_exist():
    body = text(PROMISES)
    for path in re.findall(r"`((?:scripts|harness|docs|kit|packs)/[\w./-]+)`", body):
        assert not_here_yet(path) or (REPO / path).exists(), path
    for name in re.findall(r"`(test_\w+\.py)`", body):
        assert not_here_yet(name) or (REPO / "harness" / "tests" / name).exists(), name
    for target in re.findall(r"\]\(([\w./-]+)\)", body):
        assert (KIT / target).exists(), target


def test_the_files_that_arrive_with_a_branch_are_checked_as_soon_as_it_is_merged():
    assert not_here_yet("kit/app/export.js") == (not (REPO / "kit" / "app").exists())
    assert not not_here_yet("harness/src/tonekit_harness/source.py")  # ours: always checked
