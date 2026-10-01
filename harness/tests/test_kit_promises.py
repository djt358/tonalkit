"""kit/PROMISES.md keeps the promises honest: every quotation is word for word in the file it names, every
"never" in the consent has a row, every mechanism has a status, and the checks that are already
buildable (the register row, the sign-off rule, no network client in the harness) are tests here."""

import ast
import csv
import re
from pathlib import Path

import pytest
from kit_support import CONSENT, GUIDE, KIT, PROMISES, REPO, copy, text

from tonekit_harness import provenance

DATA_REGISTER = REPO / "data-register.csv"
HARNESS_SRC = REPO / "harness" / "src"
HEADER = ["Promise", "Where we say it", "Mechanism that keeps it", "Test"]
QUOTED = re.compile(r'(CONSENT|GUIDE|copy [\w.]+) "([^"]+)"')
STATUS = re.compile(r"\(built(?:, as policy)?\)|\b(?:P4|P5|C0|E1) \(pending\)|DJ \(operational\)")

# Imports that would let the harness send audio somewhere. A tripwire, not a proof: it reads import
# statements only. Whoever needs one for a good reason changes this list on purpose (and the promise).
NETWORK_MODULES = (
    "requests", "httpx", "aiohttp", "urllib3", "urllib.request", "socket", "http.client", "http.server", "ftplib",
    "smtplib", "poplib", "imaplib", "telnetlib", "xmlrpc", "websockets", "paramiko", "grpc", "boto3", "botocore",
    "google.cloud", "azure", "tencentcloud", "huggingface_hub",
)  # fmt: skip


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
    section = text(CONSENT).split("## What we will never do\n", 1)[1].split("\n## ", 1)[0]
    return [line.removeprefix("- ") for line in section.splitlines() if line.startswith("- ")]


def network_imports(root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        names = set()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
                names.update(f"{node.module}.{alias.name}" for alias in node.names)
        bad = sorted(n for n in names if any(n == m or n.startswith(m + ".") for m in NETWORK_MODULES))
        if bad:
            found[path.relative_to(root).as_posix()] = bad
    return found


# --- the register is complete and its words are the real words --------------------------------------


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
        assert (REPO / path).exists(), path
    for name in re.findall(r"`(test_\w+\.py)`", body):
        assert (REPO / "harness" / "tests" / name).exists(), name
    for target in re.findall(r"\]\(([\w./-]+)\)", body):
        assert (KIT / target).exists(), target


# --- the volunteer recordings are in the data register, and cannot fit anything unsigned ---------------


def test_volunteer_recordings_are_registered_for_evaluation_only_until_dj_signs_off():
    with DATA_REGISTER.open(newline="", encoding="utf-8") as f:
        row = {r["id"]: r for r in csv.DictReader(f)}["volunteer-corpus"]
    assert row["kind"] == "dataset"
    assert row["shipped_weights_training"] == "verify"
    assert "calibration only after DJ confirms consent wording" in row["role"]
    assert "kit/CONSENT.md" in row["license"] and "kit/PROMISES.md" in row["notes"]


def test_a_pack_cannot_list_volunteer_recordings_as_a_source_without_a_signoff(tmp_path):
    manifest = tmp_path / "PROVENANCE.toml"
    manifest.write_text('artifact = "x"\nnote = "t"\n[[source]]\nid = "volunteer-corpus"\n', encoding="utf-8")
    (violation,) = provenance.check(DATA_REGISTER, [manifest])
    assert "source 'volunteer-corpus' is verify and has no matching [[signoff]]" in violation


def test_a_signoff_by_dj_is_what_lets_it_through(tmp_path):
    manifest = tmp_path / "PROVENANCE.toml"
    manifest.write_text(
        'artifact = "x"\nnote = "t"\n[[source]]\nid = "volunteer-corpus"\n'
        '[[signoff]]\nid = "volunteer-corpus"\nby = "DJ"\n',
        encoding="utf-8",
    )
    assert provenance.check(DATA_REGISTER, [manifest]) == []


# --- "we never send them anywhere": the harness has no way to ---------------------------------------


def test_the_harness_imports_no_network_client():
    assert network_imports(HARNESS_SRC) == {}


@pytest.mark.parametrize(
    "line",
    ["import requests", "from urllib import request", "from urllib.request import urlopen", "import socket"],
)
def test_the_scan_sees_a_network_import(tmp_path, line):
    (tmp_path / "upload.py").write_text(line + "\n", encoding="utf-8")
    assert list(network_imports(tmp_path)) == ["upload.py"]


def test_the_scan_leaves_ordinary_imports_alone(tmp_path):
    (tmp_path / "fine.py").write_text("import urllib.parse\nfrom pathlib import Path\nimport json\n", encoding="utf-8")
    assert network_imports(tmp_path) == {}
