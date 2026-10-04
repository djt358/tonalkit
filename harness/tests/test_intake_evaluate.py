"""End to end: kit bundles of a few real deck cards (gate pairs, an error card, a register card, a
minimal-set member), said by the synthetic test voice, go through `tkh intake` and `tkh evaluate`
grades the corpus to a report. Two sessions, so two speakers' copies of the same deck pairs."""

from __future__ import annotations

import shlex

from intake_support import kit_bundle, tkh

CARDS = ["r01", "r02", "g01-c", "g01-e", "g02-c", "g02-e", "m01-a", "m01-b", "x02"]


def test_bundles_taken_in_are_graded_by_tkh_evaluate(tmp_path, capsys):
    data = tmp_path / "data"
    first = kit_bundle(tmp_path / "in", "K7Q2MD", CARDS, voiced=True)
    second = kit_bundle(tmp_path / "in", "ABCDEF", CARDS[:6], skipped=CARDS[6:], folder=True, voiced=True)
    code, out, err = tkh(capsys, "intake", str(first), str(second), "--data", str(data))
    assert code == 0, err
    suggested = shlex.split(out.strip().splitlines()[-1])
    assert suggested[2:4] == ["tkh", "eval"]
    # what DJ runs next (by the name the brief uses), without touching the checkout's cache
    code, out, err = tkh(capsys, "evaluate", *suggested[4:], "--no-cache")
    assert code == 0, err
    report = data / "reports" / "volunteers-s05-v1.md"
    assert f"report written to {report}" in out
    text = report.read_text(encoding="utf-8")
    clips = next(line for line in text.splitlines() if line.startswith("- clips: "))
    assert sorted(clips.removeprefix("- clips: ").split(", ")) == [
        "diag_context 1", "diag_minimal 2", "gate 8", "register 4"
    ]  # fmt: skip
    for pair in ("K7Q2MD-g01", "K7Q2MD-g02", "ABCDEF-g01", "ABCDEF-g02"):
        assert f"| {pair} |" in text
    assert "4 gate pairs" in text and "S1: " in text
