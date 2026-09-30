"""docs/decisions.md is where the ruling ids cited in code comments are written down: every id
the repository cites has an entry, and every entry says what, why and what it costs."""

import os
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DECISIONS = REPO / "docs" / "decisions.md"
SKIPPED_DIRS = {".git", "target", ".venv", ".cache", ".ruff_cache", ".pytest_cache", "build", "node_modules"}
SOURCE_SUFFIXES = {".rs", ".py", ".swift", ".sh", ".toml", ".yml", ".md", ".csv"}
CITATION = re.compile(r"\bR(\d{1,2})\b")
ENTRY = re.compile(r"^### R(\d+): .*?(?=^## |^### |\Z)", re.S | re.M)


def entries() -> dict[int, str]:
    text = DECISIONS.read_text(encoding="utf-8")
    return {int(m.group(0).split(":")[0].removeprefix("### R")): m.group(0) for m in ENTRY.finditer(text)}


def process_ids() -> set[int]:
    text = DECISIONS.read_text(encoding="utf-8")
    section = text[text.index("\n## Process\n") :]
    return {int(n) for n in CITATION.findall(section)}


def cited_in_the_repository() -> dict[int, set[str]]:
    cited: dict[int, set[str]] = {}
    for root, dirs, files in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in SKIPPED_DIRS]
        for name in files:
            path = Path(root) / name
            if path.suffix not in SOURCE_SUFFIXES or path == DECISIONS:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for n in CITATION.findall(text):
                cited.setdefault(int(n), set()).add(str(path.relative_to(REPO)))
    return cited


def test_every_ruling_the_repository_cites_has_an_entry():
    known = set(entries()) | process_ids()
    missing = {f"R{n}": sorted(where) for n, where in cited_in_the_repository().items() if n not in known}
    assert not missing, f"cited but not in docs/decisions.md: {missing}"


def test_the_scan_finds_the_citations_it_is_meant_to_check():
    cited = cited_in_the_repository()
    assert {27, 32, 33, 43}.issubset(cited)  # cited in the Rust sources today
    assert any(path.endswith(".rs") for path in cited[27])


def test_every_entry_says_what_was_decided_why_and_what_a_mistake_costs():
    found = entries()
    assert len(found) > 30
    for n, text in found.items():
        flat = " ".join(text.split())  # the entries are wrapped, sometimes inside a label
        for part in ("**Decision.**", "**Why.**", "**Cost if wrong.**"):
            assert part in flat, f"R{n} lacks {part}"


def test_entries_are_not_repeated_and_the_process_section_does_not_duplicate_them():
    text = DECISIONS.read_text(encoding="utf-8")
    ids = [int(n) for n in re.findall(r"^### R(\d+):", text, re.M)]
    assert len(ids) == len(set(ids))
    assert not set(ids) & process_ids()


def test_every_ruling_is_either_an_entry_or_a_process_line():
    assert set(range(1, 55)) <= set(entries()) | process_ids()


def test_the_readme_points_at_the_decisions():
    assert "docs/decisions.md" in (REPO / "README.md").read_text(encoding="utf-8")
