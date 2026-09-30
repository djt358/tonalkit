"""The two licence registers (data-register.csv, read by `tkh provenance`, and the research copy
in docs/research) agree, and say what the final review required of them."""

import csv
from pathlib import Path

from tonekit_harness import provenance

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "data-register.csv"
RESEARCH = REPO / "docs" / "research" / "tone-assessment-license-register.csv"
COLUMNS = [
    "id", "kind", "name", "license", "commercial_ok", "shipped_code",
    "shipped_weights_training", "role", "verified_via", "source_url", "notes",
]  # fmt: skip


def rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == COLUMNS
        return {r["id"]: r for r in reader}


def test_both_registers_hold_the_same_rows():
    assert rows(DATA) == rows(RESEARCH)


def test_every_row_has_every_column():
    for path in (DATA, RESEARCH):
        for row in rows(path).values():
            assert None not in row and None not in row.values(), row["id"]  # no ragged rows


def test_swift_f0_weights_are_unverified_until_its_training_data_is_cleared():
    for path in (DATA, RESEARCH):
        row = rows(path)["swift-f0"]
        assert row["shipped_weights_training"] == "verify"
        assert "training data (swift-f0-training repo) licences unchecked" in row["notes"]
        assert "spec §11.2" in row["notes"]


def test_a_pack_cannot_ship_swift_f0_weights_without_a_signoff(tmp_path):
    manifest = tmp_path / "PROVENANCE.toml"
    manifest.write_text('artifact = "x"\nnote = "t"\n[[source]]\nid = "swift-f0"\n', encoding="utf-8")
    (violation,) = provenance.check(DATA, [manifest])
    assert "source 'swift-f0' is verify and has no matching [[signoff]]" in violation


def test_target_lexicon_is_a_build_time_only_row():
    for path in (DATA, RESEARCH):
        row = rows(path)["target-lexicon"]
        assert row["license"] == "Apache-2.0 WITH LLVM-exception"
        assert "build-time only" in row["role"]
        assert row["shipped_code"] == row["shipped_weights_training"] == "n/a"
        assert "R44" in row["notes"]


def test_pyo3_and_maturin_are_pinned_not_left_to_verify_at_pin():
    for path in (DATA, RESEARCH):
        table = rows(path)
        assert "0.29.2" in table["pyo3"]["verified_via"]
        assert "1.15.0" in table["maturin"]["verified_via"]
        assert "verify at pin" not in table["pyo3"]["verified_via"] + table["maturin"]["verified_via"]
