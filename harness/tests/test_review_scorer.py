"""The scorer's view on the review page: each clip's group and doubt, from hand-made results."""

from __future__ import annotations

import pytest

from tonekit_harness.eval_results import ClipResult, SyllableResult
from tonekit_harness.manifest import Candidate, Clip, Condition
from tonekit_harness.review.scorer import AGREES, DISAGREES, NOT_GRADED, TWIN, UNSURE, scorer_view

INTENDED = ["4", "1", "3"]
ERROR_CARD = ["4", "1", "4"]  # its twin, the correct card, asks for INTENDED


def clip(asked: list[str]) -> Clip:
    label = "correct" if asked == INTENDED else "tone_error"
    return Clip(id="K7Q2MD-g01-x", path="a.wav", speaker="v-k7q2md", set="gate", pair="K7Q2MD-g01", label=label,
                intended=Candidate(id="g01", tones=INTENDED, labels=["yi", "bei", "shui"]), produced_tones=asked,
                condition=Condition(noise="n", distance="d"), source="volunteer-corpus")  # fmt: skip


def result(heard: list[str | None], p: list[float], overall: float | None = 0.5, issues=None) -> ClipResult:
    syllables = [
        SyllableResult(expected=e, heard=h, p_correct=q, distance=1.0, measured="Full", issues=(issues or {}).get(i, []))
        for i, (e, h, q) in enumerate(zip(INTENDED, heard, p, strict=True))
    ]
    return ClipResult(id="K7Q2MD-g01-x", set="gate", pair="K7Q2MD-g01", label="x", speaker="v", overall=overall,
                      intended_rank=1, margin_llr=0.0, register_source="cold", syllables=syllables)  # fmt: skip


@pytest.mark.parametrize(
    ("asked", "twin", "heard", "p", "group"),
    [
        # an error card heard as the correct word, or leaning to it without a confident tone
        (ERROR_CARD, INTENDED, ["4", "1", "3"], [0.9, 0.9, 0.9], TWIN),
        (ERROR_CARD, INTENDED, ["4", "1", None], [0.9, 0.9, 0.7], TWIN),
        (ERROR_CARD, INTENDED, ["4", "1", None], [0.9, 0.9, 0.3], AGREES),
        # a correct card heard as the error word
        (INTENDED, ERROR_CARD, ["4", "1", "4"], [0.9, 0.9, 0.05], TWIN),
        # a correct card with only a low p_correct where its twin differs: no tone of the twin heard
        (INTENDED, ERROR_CARD, ["4", "1", None], [0.9, 0.9, 0.2], UNSURE),
        # another tone heard where the twin does not differ
        (INTENDED, ERROR_CARD, ["4", "2", "3"], [0.9, 0.05, 0.9], DISAGREES),
        # no pair: never TWIN
        (ERROR_CARD, None, ["4", "1", "3"], [0.9, 0.9, 0.9], DISAGREES),
        (INTENDED, ERROR_CARD, ["4", "1", "3"], [0.9, 0.8, 0.9], AGREES),
    ],
)
def test_groups(asked, twin, heard, p, group):
    assert scorer_view(clip(asked), result(heard, p), twin).group == group


def test_doubt_is_how_likely_the_cards_tone_was_not_said():
    view = scorer_view(clip(ERROR_CARD), result(["4", "1", None], [0.8, 0.95, 0.3]), INTENDED)
    # 1 - p where the card asks for the intended tone; p (of the intended tone) where it asks for the error
    assert [round(s.doubt, 2) for s in view.syllables] == [0.2, 0.05, 0.3] and view.doubt == pytest.approx(0.3)


def test_a_syllable_with_no_nucleus_has_no_doubt_and_an_unscored_clip_is_unsure():
    view = scorer_view(clip(INTENDED), result(["4", "1", None], [0.9, 0.9, 0.047], None, {2: ["NoNucleus"]}))
    assert view.group == UNSURE and view.doubt == 1.0
    assert view.syllables[2].doubt is None and view.syllables[2].note == "not measured"


def test_a_clip_with_no_results_is_not_graded():
    assert scorer_view(clip(INTENDED), None).group == NOT_GRADED
