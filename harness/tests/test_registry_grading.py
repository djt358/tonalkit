"""A selection composed from several corpora grades with `evaluate.run` as it stands: qualified
ids keep the corpora's speakers and clips apart, and `clearance` agrees with the registry's gate."""

from __future__ import annotations

from pathlib import Path

import pytest
from registry_support import REGISTER, add_corpus, speaker
from support import make_clip

from tonekit_harness import clearance, evaluate
from tonekit_harness.registry import DataRoot

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"


@pytest.fixture(scope="module")
def two_labs(tmp_path_factory) -> DataRoot:
    """lab-a and lab-b: each has a speaker `dj` with the same two clip ids, audio synthesised."""
    root = tmp_path_factory.mktemp("two-labs")
    for lab, seed in (("lab-a", 0), ("lab-b", 1)):
        audio = root / "corpora" / lab / "audio"
        clips = [
            make_clip(audio, "g1-c", ["4", "1", "3"], pair="g1", label="correct", source="dj-corpus", seed=seed),
            make_clip(audio, "g1-e", ["4", "2", "3"], intended=["4", "1", "3"], pair="g1", label="tone_error",
                      source="dj-corpus", seed=seed),
        ]  # fmt: skip
        clips = [c.model_copy(update={"path": f"audio/{c.path}", "speaker": "dj"}) for c in clips]
        add_corpus(root, lab, kind="recorded", source="dj-corpus", speakers=[speaker("dj")], clips=clips)
    return DataRoot(root)


def test_clips_of_two_corpora_with_the_same_ids_and_speaker_grade_together(two_labs):
    selection = two_labs.select(kinds=["recorded"], splits=["gate"], sets=["gate"]).for_gate(REGISTER)
    clips = selection.grading_clips()
    results = evaluate.run(
        clips,
        (PACKS / "cmn.toml").read_text(encoding="utf-8"),
        None,
        None,
        root=selection.audio_root,
        use_cache=False,
    )
    assert [r.id for r in results] == ["lab-a/g1-c", "lab-a/g1-e", "lab-b/g1-c", "lab-b/g1-e"]
    assert [r.speaker for r in results] == ["lab-a/dj", "lab-a/dj", "lab-b/dj", "lab-b/dj"]
    assert all(r.syllables for r in results)  # the audio was found under each corpus's own directory


def test_clearance_and_the_registry_agree_on_a_gate(two_labs):
    selection = two_labs.select()
    selection.for_gate(REGISTER)
    assert clearance.assess(selection.grading_clips(), REGISTER).verdict


def test_clearance_and_the_registry_agree_on_a_refused_gate(two_labs):
    selection = two_labs.select()
    register = {**REGISTER, "dj-corpus": "verify"}
    assert not clearance.assess(selection.grading_clips(), register).verdict
    with pytest.raises(ValueError, match="dj-corpus' is 'verify'"):
        selection.for_gate(register)
