"""`tkh eval --results`: the per-clip results file (`tonekit.eval-results.v1`) that `tkh review`
reads, written from hand-built results."""

from __future__ import annotations

import json
import math

import pytest

from tonekit_harness.eval_results import ResultsError, load_results, results_document, write_results
from tonekit_harness.evaluate import Result, Syllable


def _result(cid: str = "K7Q2MD-g01-e", margin: float = 1.5) -> Result:
    return Result(
        id=cid,
        set="gate",
        pair="K7Q2MD-g01",
        label="tone_error",
        speaker="v-k7q2md",
        overall=0.41,
        intended_rank=1,
        margin_llr=margin,
        syllables=[
            Syllable("4", "4", 0.9, 0.3, "Full"),
            Syllable("1", "2", 0.2, 1.1, "Partial", [("WiderRange", 1.0)], ["CreakyTail"]),
            Syllable("3", None, 0.047, None, "NotMeasured", [], ["NoNucleus"]),
        ],
        register_source="given",
        issues=["LowSnr"],
    )


def test_the_results_file_round_trips_every_clip_and_syllable(tmp_path):
    path = tmp_path / "reports" / "c.results.json"
    write_results(path, results_document([_result()], register_from="speaker", tonekit_py="0.1+abc"))
    doc = load_results(path)
    assert json.loads(path.read_text())["schema"] == "tonekit.eval-results.v1"
    assert (doc.register_from, doc.tonekit_py) == ("speaker", "0.1+abc")
    [clip] = doc.clips
    assert (clip.id, clip.pair, clip.label, clip.overall, clip.issues) == (
        "K7Q2MD-g01-e", "K7Q2MD-g01", "tone_error", 0.41, ["LowSnr"]
    )  # fmt: skip
    assert [(s.expected, s.heard, s.p_correct) for s in clip.syllables] == [
        ("4", "4", 0.9), ("1", "2", 0.2), ("3", None, 0.047)
    ]  # fmt: skip
    # read back as evaluate's syllables, whose properties say how each was measured
    assert [s.syllable().fallback for s in clip.syllables] == [False, False, True]


def test_a_margin_that_is_not_finite_is_written_as_null(tmp_path):
    path = tmp_path / "r.json"
    write_results(path, results_document([_result(margin=math.inf)], register_from="drill", tonekit_py="x"))
    assert json.loads(path.read_text())["clips"][0]["margin_llr"] is None
    assert load_results(path).clips[0].margin_llr is None


@pytest.mark.parametrize("text", ["not json", '{"schema": "tonekit.eval-results.v0", "clips": []}'])
def test_a_file_that_is_not_a_results_file_is_refused_naming_it(tmp_path, text):
    path = tmp_path / "r.json"
    path.write_text(text)
    with pytest.raises(ResultsError, match=str(path)):
        load_results(path)


def test_a_missing_results_file_is_refused_naming_it(tmp_path):
    with pytest.raises(ResultsError, match="cannot read"):
        load_results(tmp_path / "none.json")
