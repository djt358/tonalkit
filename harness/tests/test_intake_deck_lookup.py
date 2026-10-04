"""Finding the deck a bundle was recorded with, by the sha256 of the JSON the phone fetched."""

from __future__ import annotations

import hashlib
import json
import subprocess

import pytest
from intake_support import DECK_ID, DECK_JSON, deck_sha

from tonekit_harness.contracts.bundle import DeckRef
from tonekit_harness.intake.deck_lookup import find_deck
from tonekit_harness.intake.errors import IntakeError
from tonekit_harness.repo import repo_root


def ref(sha: str, deck_id: str = DECK_ID) -> DeckRef:
    return DeckRef(id=deck_id, sha256=sha)


def other_version() -> bytes:
    """The real deck with a different title: another file, the same cards."""
    doc = json.loads(DECK_JSON.read_text(encoding="utf-8"))
    doc["deck"]["title"] = "an older title"
    return (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode()


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def history_repo(tmp_path, versions: list[bytes]):
    """A git repository whose kit/deck/s05-v1.json went through `versions` (the last is checked out)."""
    repo = tmp_path / "repo"
    (repo / "kit" / "deck").mkdir(parents=True)
    git(repo, "init", "-q")
    for i, data in enumerate(versions):
        (repo / "kit" / "deck" / f"{DECK_ID}.json").write_bytes(data)
        git(repo, "add", ".")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", f"v{i}")
    return repo


def test_the_repository_deck_file_with_the_bundles_hash_is_used():
    found = find_deck(ref(deck_sha()), repo=repo_root())
    assert found.where == f"kit/deck/{DECK_ID}.json"
    assert found.deck.deck.id == DECK_ID and len(found.deck.card) == 76


def test_an_explicit_deck_file_with_the_bundles_hash_is_used(tmp_path):
    path = tmp_path / "served.json"
    path.write_bytes(other_version())
    found = find_deck(ref(hashlib.sha256(other_version()).hexdigest()), repo=tmp_path, explicit=path)
    assert found.where == str(path) and found.deck.deck.title == "an older title"


def test_an_explicit_deck_file_with_another_hash_is_refused_naming_both(tmp_path):
    path = tmp_path / "served.json"
    path.write_bytes(other_version())
    with pytest.raises(IntakeError) as e:
        find_deck(ref(deck_sha()), repo=repo_root(), explicit=path)
    assert hashlib.sha256(other_version()).hexdigest() in str(e.value) and deck_sha() in str(e.value)
    assert "--deck" in str(e.value)


def test_an_older_committed_version_with_the_bundles_hash_is_found_in_git_history(tmp_path):
    old = other_version()
    repo = history_repo(tmp_path, [old, DECK_JSON.read_bytes()])
    found = find_deck(ref(hashlib.sha256(old).hexdigest()), repo=repo)
    assert found.where.startswith(f"kit/deck/{DECK_ID}.json at commit ")
    assert found.deck.deck.title == "an older title"


def test_no_matching_version_is_refused_naming_both_hashes_and_how_to_pass_deck(tmp_path):
    repo = history_repo(tmp_path, [DECK_JSON.read_bytes()])
    wanted = "ab" * 32
    with pytest.raises(IntakeError) as e:
        find_deck(ref(wanted), repo=repo)
    message = str(e.value)
    assert wanted in message and deck_sha() in message
    assert "1 committed version(s)" in message and "--deck PATH" in message


def test_a_repository_without_the_deck_or_git_is_refused(tmp_path):
    with pytest.raises(IntakeError, match="does not exist.*--deck PATH"):
        find_deck(ref("ab" * 32), repo=tmp_path)


def test_a_matching_file_that_is_not_a_deck_is_refused(tmp_path):
    path = tmp_path / "x.json"
    path.write_bytes(b"[1, 2]")
    with pytest.raises(IntakeError, match="not a deck JSON file"):
        find_deck(ref(hashlib.sha256(b"[1, 2]").hexdigest()), repo=tmp_path, explicit=path)
