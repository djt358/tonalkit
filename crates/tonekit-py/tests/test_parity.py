"""The Python module gives the CLI's numbers: `fixtures/spoken-413.wav` through
`tonekit_py.analyze` + `assess` reproduces `fixtures/spoken-413.assessment.json`.

The shared fixture is what the Rust CLI printed and what the Swift tests on the iOS Simulator
must reproduce. Comparison is by parsed value (ruling R41): every number within 1e-4, and
everything else (strings, booleans, nulls, array lengths, object keys) identical.
"""

from __future__ import annotations

import json
import math

import pytest
import tonekit_py

from support import RATE, request_413

TOLERANCE = 1e-4


def json_max_diff(want, got, tol: float = TOLERANCE, path: str = "$") -> float:
    """The largest numeric |want - got| anywhere in two parsed JSON values.

    Raises AssertionError at the first place they differ: a number off by more than `tol`, or a
    string, bool, null, array length, object key or type that is not identical.
    """
    if isinstance(want, bool) or isinstance(got, bool) or want is None or got is None:
        assert want == got and type(want) is type(got), f"{path}: {want!r} vs {got!r}"
        return 0.0
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        diff = abs(float(want) - float(got))
        assert not math.isnan(diff) and diff <= tol, f"{path}: {want} vs {got} (|diff| {diff:e})"
        return diff
    if isinstance(want, list) and isinstance(got, list):
        assert len(want) == len(got), f"{path}: {len(want)} elements vs {len(got)}"
        return max(
            (json_max_diff(w, g, tol, f"{path}[{i}]") for i, (w, g) in enumerate(zip(want, got))),
            default=0.0,
        )
    if isinstance(want, dict) and isinstance(got, dict):
        assert want.keys() == got.keys(), (
            f"{path}: keys differ (only in want: {sorted(want.keys() - got.keys())}, "
            f"only in got: {sorted(got.keys() - want.keys())})"
        )
        return max((json_max_diff(want[k], got[k], tol, f"{path}.{k}") for k in want), default=0.0)
    assert want == got and type(want) is type(got), f"{path}: {want!r} vs {got!r}"
    return 0.0


def grade_fixture(pcm, pack_toml, calib_json) -> dict:
    analysis_json = tonekit_py.analyze(pcm, RATE)
    assessment_json = tonekit_py.assess(
        analysis_json, pack_toml, calib_json, json.dumps(request_413())
    )
    return json.loads(assessment_json)


def test_the_spoken_fixture_reproduces_the_cli_assessment(
    pcm, pack_toml, calib_json, expected_assessment, capsys
):
    got = grade_fixture(pcm, pack_toml, calib_json)
    max_diff = json_max_diff(expected_assessment, got)
    with capsys.disabled():
        print(f"\nparity: json max |diff| vs fixtures/spoken-413.assessment.json = {max_diff:e}")

    # The three things the Swift test asserts, spelled out.
    assert got["schema"] == "tonekit.assessment.v1"
    assert got["intended_rank"] == 1
    assert abs(got["overall"] - expected_assessment["overall"]) < TOLERANCE
    assert [s["expected"] for s in got["syllables"]] == ["4", "1", "3"]


def test_the_comparison_helper_catches_a_drift():
    """The parity check above is only worth something if json_max_diff can fail."""
    want = {"a": [1.0, {"b": "x", "c": None}], "d": True}
    assert json_max_diff(want, json.loads(json.dumps(want))) == 0.0
    assert json_max_diff(want, {"a": [1.00005, {"b": "x", "c": None}], "d": True}) > 0.0
    for bad in (
        {"a": [1.001, {"b": "x", "c": None}], "d": True},  # number off by more than 1e-4
        {"a": [1.0, {"b": "y", "c": None}], "d": True},  # string differs
        {"a": [1.0, {"b": "x", "c": 0}], "d": True},  # null vs number
        {"a": [1.0], "d": True},  # array length
        {"a": [1.0, {"b": "x", "c": None}], "d": 1},  # bool vs number
        {"a": [1.0, {"b": "x", "c": None}], "d": True, "e": 0},  # extra key
    ):
        with pytest.raises(AssertionError):
            json_max_diff(want, bad)
