"""docs/decisions.md is where the ruling ids cited in code comments are written down: every id
the repository cites has an entry, and every entry says what, why and what it costs."""

import fnmatch
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DECISIONS = REPO / "docs" / "decisions.md"
SKIPPED_DIRS = {"target", "build", "node_modules", "__pycache__"}
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


def tracked_files(repo: Path) -> list[Path]:
    """The files the repository ships: `git ls-files` from its root, so untracked and git-ignored
    working files (the `.superpowers/` ledger, scratch notes) are never scanned. Outside a git
    checkout (an exported tarball) it falls back to a walk that skips dot-directories and whatever
    the top-level `.gitignore` names."""
    listed = _git_ls_files(repo)
    return listed if listed is not None else _walk_shipped(repo)


def _git_ls_files(repo: Path) -> list[Path] | None:
    try:
        top = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--show-toplevel"], capture_output=True, check=True, text=True
        ).stdout.strip()
        if Path(top).resolve() != repo.resolve():  # `repo` sits inside some other checkout
            return None
        out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return [repo / name for name in out.decode("utf-8").split("\0") if name]


def _gitignore_patterns(repo: Path) -> list[str]:
    try:
        lines = (repo / ".gitignore").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    return [line.strip() for line in lines if line.strip() and not line.startswith(("#", "!"))]


def _is_ignored(relative: str, patterns: list[str]) -> bool:
    name = relative.rsplit("/", 1)[-1]
    for pattern in patterns:
        bare = pattern.strip("/")
        if pattern.startswith("/") or "/" in bare:  # anchored at the repository root
            if fnmatch.fnmatch(relative, bare):
                return True
        elif fnmatch.fnmatch(name, bare):
            return True
    return False


def _walk_shipped(repo: Path) -> list[Path]:
    patterns = _gitignore_patterns(repo)
    found: list[Path] = []
    for root, dirs, files in os.walk(repo):
        base = Path(root).relative_to(repo)
        dirs[:] = [
            d
            for d in dirs
            if not d.startswith(".") and d not in SKIPPED_DIRS and not _is_ignored((base / d).as_posix(), patterns)
        ]
        found += [Path(root) / f for f in files if not _is_ignored((base / f).as_posix(), patterns)]
    return found


def cited_in(repo: Path) -> dict[int, set[str]]:
    cited: dict[int, set[str]] = {}
    for path in tracked_files(repo):
        if path.suffix not in SOURCE_SUFFIXES or path == repo / "docs" / "decisions.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for n in CITATION.findall(text):
            cited.setdefault(int(n), set()).add(path.relative_to(repo).as_posix())
    return cited


def cited_in_the_repository() -> dict[int, set[str]]:
    return cited_in(REPO)


def test_every_ruling_the_repository_cites_has_an_entry():
    known = set(entries()) | process_ids()
    missing = {f"R{n}": sorted(where) for n, where in cited_in_the_repository().items() if n not in known}
    assert not missing, f"cited but not in docs/decisions.md: {missing}"


def test_the_scan_finds_the_citations_it_is_meant_to_check():
    cited = cited_in_the_repository()
    assert {27, 32, 33, 43}.issubset(cited)  # cited in the Rust sources today
    assert any(path.endswith(".rs") for path in cited[27])


def _write(root: Path, name: str, *cited: int) -> None:
    """A file that cites the given ids. The ids are spelled out here, not in the test bodies, so
    that the scan of this very file does not see them as citations."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"see R{n}\n" for n in cited), encoding="utf-8")


def _ignore(root: Path, *patterns: str) -> None:
    (root / ".gitignore").write_text("".join(f"{p}\n" for p in patterns), encoding="utf-8")


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_the_scan_reads_tracked_files_only(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    _write(tmp_path, "src/lib.rs", 7)
    _ignore(tmp_path, "/scratch/")
    _write(tmp_path, "notes.md", 8)  # in the working tree, not added
    _write(tmp_path, "scratch/ledger.md", 99)  # git-ignored
    _write(tmp_path, ".superpowers/progress.md", 98)  # untracked dot-directory
    subprocess.run(["git", "-C", str(tmp_path), "add", "src/lib.rs", ".gitignore"], check=True)
    assert cited_in(tmp_path) == {7: {"src/lib.rs"}}


def test_without_git_the_scan_skips_dot_directories_and_ignored_paths(tmp_path):
    _ignore(tmp_path, "# scratch", "/scratch/", "*.log", "target/")
    _write(tmp_path, "src/lib.rs", 7)
    _write(tmp_path, "docs/decisions.md", 5)
    _write(tmp_path, "docs/guide.md", 6)
    _write(tmp_path, "scratch/ledger.md", 99)
    _write(tmp_path, "src/debug.log", 97)
    _write(tmp_path, "crates/x/target/notes.md", 96)
    _write(tmp_path, ".superpowers/progress.md", 98)
    _write(tmp_path, "src/image.bin", 95)
    assert cited_in(tmp_path) == {7: {"src/lib.rs"}, 6: {"docs/guide.md"}}


def test_a_checkout_nested_in_another_one_is_not_read_through_the_outer_git(tmp_path):
    inner = tmp_path / "inner"
    _write(inner, "src/lib.rs", 7)
    _write(inner, "drafts/.hidden/x.md", 9)
    if shutil.which("git") is not None:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    assert cited_in(inner) == {7: {"src/lib.rs"}}


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
    assert set(range(1, 58)) <= set(entries()) | process_ids()


def test_the_readme_points_at_the_decisions():
    assert "docs/decisions.md" in (REPO / "README.md").read_text(encoding="utf-8")
