"""The volunteer recordings in the data register (R72, R79), and what a listing in a PROVENANCE.toml
does with them: they are cleared for evaluation and calibration, so no sign-off is asked for."""

import csv

import pytest
from kit_support import REPO

from tonekit_harness import provenance

REGISTERS = [REPO / "data-register.csv", REPO / "docs" / "research" / "tone-assessment-license-register.csv"]


def row(path, row_id: str) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as f:
        return {r["id"]: r for r in csv.DictReader(f)}[row_id]


def manifest(tmp_path, *sources: str, signoffs: tuple[str, ...] = ()) -> list:
    lines = ['artifact = "x"', 'note = "t"']
    lines += [f'[[source]]\nid = "{s}"' for s in sources]
    lines += [f'[[signoff]]\nid = "{s}"\nby = "DJ"' for s in signoffs]
    path = tmp_path / "PROVENANCE.toml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [path]


@pytest.mark.parametrize("path", REGISTERS, ids=["data-register", "research copy"])
def test_the_volunteer_row_is_cleared_for_evaluation_and_calibration(path):
    volunteers = row(path, "volunteer-corpus")
    assert volunteers["kind"] == "dataset"
    assert volunteers["commercial_ok"] == "yes (evaluation and calibration)"
    assert volunteers["shipped_weights_training"] == "allow"
    assert volunteers["role"] == "S1 gate, evaluation and calibration for tonekit and Bendy; consent v1"
    assert "kit/CONSENT.md" in volunteers["license"]
    assert "kit/CONSENT.md" in volunteers["verified_via"] and "kit/PROMISES.md" in volunteers["verified_via"]
    assert "audit pending" not in volunteers["verified_via"]  # the row says allow, so it cannot also wait
    assert "never resynthesised" in volunteers["notes"] and "gate split" in volunteers["notes"]


def test_a_pack_fitted_on_volunteer_recordings_passes_without_a_signoff(tmp_path):
    assert provenance.check(REGISTERS[0], manifest(tmp_path, "volunteer-corpus")) == []


def test_a_verify_source_without_a_signoff_is_a_violation(tmp_path):
    (violation,) = provenance.check(REGISTERS[0], manifest(tmp_path, "swift-f0"))
    assert "source 'swift-f0' is verify and has no matching [[signoff]]" in violation


def test_a_signoff_by_dj_is_what_lets_a_verify_source_through(tmp_path):
    assert provenance.check(REGISTERS[0], manifest(tmp_path, "swift-f0", signoffs=("swift-f0",))) == []
