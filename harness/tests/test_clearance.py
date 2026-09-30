"""Whether a run's clips may back the S1 gate verdict: only real recordings whose source the data
register allows (spec §9, §13); synthetic audio never does."""

from pathlib import Path

import pytest

from tonekit_harness import clearance, provenance
from tonekit_harness.clearance import Clearance
from tonekit_harness.manifest import Clip, ManifestError

REGISTER = provenance.load_register(Path(__file__).resolve().parents[2] / "data-register.csv")


def clip(cid: str = "c", *, set: str = "gate", source: str = "dj-corpus", synthetic=None) -> Clip:
    return Clip.model_validate(
        {
            "id": cid,
            "path": f"{cid}.wav",
            "speaker": "dj",
            "set": set,
            "pair": None,
            "label": "correct",
            "intended": {"id": "x", "tones": ["4"], "labels": []},
            "condition": {"noise": "cafe", "distance": "arm"},
            "source": source,
            "synthetic": synthetic,
        }
    )


REAL = clip("real")
WORLD = clip("world", source="synthetic-world")  # a synthetic clip standing in the gate set


def assess(clips, **kw) -> Clearance:
    return clearance.assess(clips, REGISTER, **kw)


# ---- which clips are synthetic, which sources are allowed --------------------------------------


def test_the_synthetic_world_source_is_synthetic():
    assert clearance.is_synthetic(WORLD)


def test_a_synthetic_field_makes_a_clip_synthetic_whatever_its_source():
    # `Clip` refuses the field outside set "synthetic", so make such a row the way a caller could
    sneaky = REAL.model_copy(update={"synthetic": {"from": "gate-01-correct"}})
    assert clearance.is_synthetic(sneaky)


def test_the_synthetic_set_is_synthetic():
    assert clearance.is_synthetic(clip("s", set="synthetic", synthetic={"from": "x"}))


def test_a_recording_is_not_synthetic():
    assert not clearance.is_synthetic(REAL)


@pytest.mark.parametrize(
    ("source", "allowed"),
    [
        ("dj-corpus", True),  # allow
        ("aishell-3", True),
        ("synthetic-world", False),  # deny
        ("magicdata-read", False),  # deny
        ("latic", False),  # verify: not cleared until someone signs it off
        ("made-up", False),  # not in the register at all
    ],
)
def test_a_source_is_allowed_only_when_the_register_says_allow(source, allowed):
    assert clearance.is_allowed(clip(source=source), REGISTER) is allowed


# ---- the verdict -------------------------------------------------------------------------------


def test_recordings_from_allowed_sources_may_issue_the_verdict():
    got = assess([REAL, clip("r2", source="common-voice")])
    assert got == Clearance("gate", 0) and got.verdict and got.label is None


def test_a_synthetic_clip_is_not_a_gate():
    got = assess([REAL, WORLD])
    assert got.mode == "not a gate" and got.uncleared == 1 and not got.verdict
    assert got.label == "NOT A GATE (1 synthetic / non-allowed clips)"


def test_a_clip_from_a_source_that_is_not_allowed_is_not_a_gate():
    got = assess([REAL, clip("v", source="latic"), clip("d", source="magicdata-read")])
    assert (got.mode, got.uncleared) == ("not a gate", 2)


def test_a_clip_that_is_both_synthetic_and_not_allowed_counts_once():
    assert assess([REAL, WORLD, WORLD.model_copy(update={"id": "w2"})]).uncleared == 2


def test_allow_synthetic_turns_a_synthetic_run_into_a_smoke_run():
    got = assess([REAL, WORLD], allow_synthetic=True)
    assert (got.mode, got.uncleared, got.verdict) == ("smoke", 1, False)
    assert got.label == "SMOKE (synthetic)"


def test_allow_synthetic_does_not_excuse_a_real_recording_the_register_does_not_allow():
    got = assess([WORLD, clip("v", source="latic")], allow_synthetic=True)
    assert (got.mode, got.uncleared) == ("not a gate", 2)


def test_allow_synthetic_changes_nothing_for_a_corpus_of_recordings():
    assert assess([REAL], allow_synthetic=True) == Clearance("gate", 0)


def test_a_corpus_with_no_clips_has_nothing_to_object_to():
    assert assess([]) == Clearance("gate", 0)


# ---- synthetic clips may not be mixed into a gate manifest -------------------------------------


@pytest.mark.parametrize("allow", [False, True])
def test_synthetic_set_rows_mixed_with_gate_rows_are_an_error(allow):
    synthetic = clip("s", set="synthetic", source="synthetic-world", synthetic={"from": "g"})
    with pytest.raises(ManifestError, match=r"1 synthetic clip.*mixed with gate clips"):
        assess([REAL, synthetic], allow_synthetic=allow)


def test_synthetic_set_rows_alone_are_not_a_mix():
    synthetic = clip("s", set="synthetic", source="synthetic-world", synthetic={"from": "g"})
    assert assess([synthetic], allow_synthetic=True).mode == "smoke"
