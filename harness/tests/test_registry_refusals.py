"""The promises kept by mechanism: fitting never sees gate or heldout speakers or uncleared sources,
and a gate is never graded on synthetic data or uncleared sources."""

from __future__ import annotations

import pytest
from registry_support import (
    CALIB,
    DEV,
    HELDOUT,
    REGISTER,
    add_corpus,
    build_composed_root,
    ids_in_split,
    speaker,
    speaker_clips,
)

from tonekit_harness import clearance
from tonekit_harness.registry import DataRoot, FittingSelection, GateSelection, RefusalError
from tonekit_harness.registry.errors import MAX_PROBLEMS_SHOWN


@pytest.fixture
def data(tmp_path):
    return DataRoot(build_composed_root(tmp_path))


# ---- fitting --------------------------------------------------------------------------------


def test_fitting_on_public_calib_and_dev_is_allowed(data):
    selection = data.select(["aishell3"], splits=["calib", "dev"])
    checked = selection.for_fitting(REGISTER)  # returned, so it chains
    assert isinstance(checked, FittingSelection) and checked.items == selection.items
    assert not isinstance(selection, FittingSelection)  # the check is in the type, not the object asked


def test_fitting_on_a_gate_speaker_is_refused_with_the_corpus_and_speaker(data):
    with pytest.raises(RefusalError) as e:
        data.select(["volunteers-*"], splits=["gate"]).for_fitting(REGISTER)
    text = str(e.value)
    assert text.startswith("refusing to fit parameters on this selection:")
    assert "volunteers-2026-10/v-k7q2md: speaker is in split 'gate' (3 clips)" in text
    assert "volunteers-2026-10/v-abcde2: speaker is in split 'gate' (3 clips)" in text
    assert "never sees gate or heldout speakers" in text


def test_fitting_on_a_heldout_speaker_is_refused(data):
    with pytest.raises(RefusalError, match=rf"aishell3/{HELDOUT}: speaker is in split 'heldout' \(2 clips\)"):
        data.select(["aishell3"]).for_fitting(REGISTER)


def test_composing_calib_with_gate_speakers_cannot_launder_them_into_a_fit(data):
    fit = data.select(kinds=["public"], splits=["calib"])
    gate = data.select(["dj-*"], splits=["gate"])
    fit.for_fitting(REGISTER)  # fine alone
    with pytest.raises(RefusalError) as e:
        (fit | gate).for_fitting(REGISTER)
    assert "dj-2026-10/dj" in str(e.value) and CALIB not in str(e.value)  # only the offender is named


def test_dev_speakers_may_be_fitted_on_but_the_heldout_ones_next_to_them_may_not(data):
    data.select(["aishell3"], splits=["dev"]).for_fitting(REGISTER)
    with pytest.raises(RefusalError, match="heldout"):
        data.select(["aishell3"], splits=["dev", "heldout"]).for_fitting(REGISTER)


@pytest.mark.parametrize(
    "source,why",
    [
        ("latic", "source 'latic' is 'verify' in the data register, not 'allow'"),
        ("magicdata-read", "source 'magicdata-read' is 'deny' in the data register, not 'allow'"),
        ("not-a-source", "source 'not-a-source' is not in the data register"),
    ],
)
def test_fitting_on_a_source_the_register_does_not_clear_is_refused(tmp_path, source, why):
    add_corpus(tmp_path, "l2", kind="public", source=source, speakers=[speaker(CALIB, "calib")],
               clips=speaker_clips(CALIB, source))  # fmt: skip
    with pytest.raises(RefusalError, match=rf"l2: {why} \(2 clips\)"):
        DataRoot(tmp_path).select().for_fitting(REGISTER)


def test_fitting_on_synthetic_clips_is_refused_because_their_source_is_deny(data):
    with pytest.raises(RefusalError, match=r"smoke: source 'synthetic-world' is 'deny' in the data register"):
        data.select(["smoke"]).for_fitting(REGISTER)


def test_every_problem_is_listed_not_only_the_first(data):
    with pytest.raises(RefusalError) as e:
        data.select().for_fitting(REGISTER)
    text = str(e.value)
    for expected in ("volunteers-2026-10/v-k7q2md", "dj-2026-10/dj", f"aishell3/{HELDOUT}", "smoke: source 'synthetic-world'"):
        assert expected in text
    assert f"aishell3/{CALIB}" not in text and f"aishell3/{DEV}" not in text


def test_a_long_list_of_problems_is_cut_short(tmp_path):
    speakers = [speaker(i, "heldout") for i in ids_in_split("heldout", MAX_PROBLEMS_SHOWN + 3)]
    clips = [c for s in speakers for c in speaker_clips(s["id"], "aishell-3", n=1)]
    add_corpus(tmp_path, "big", kind="public", source="aishell-3", speakers=speakers, clips=clips)
    with pytest.raises(RefusalError) as e:
        DataRoot(tmp_path).select().for_fitting(REGISTER)
    assert str(e.value).count("speaker is in split 'heldout'") == MAX_PROBLEMS_SHOWN
    assert str(e.value).endswith("and 3 more")


def test_an_empty_selection_is_refused_rather_than_passing_vacuously(data):
    empty = data.select(["later-*"])  # a glob may match nothing (a gate file names corpora to come)
    assert len(empty) == 0
    for check, headline in [(empty.for_fitting, "fit parameters"), (empty.for_gate, "grade a gate")]:
        with pytest.raises(RefusalError) as e:
            check(REGISTER)
        assert str(e.value) == (
            f"refusing to {headline} on this selection:\n"
            "  the selection is empty: no clip matches the corpora, splits and sets asked for"
        )


def test_a_union_of_checked_selections_must_be_checked_again(data):
    fit = data.select(["aishell3"], splits=["calib"]).for_fitting(REGISTER)
    union = fit | data.select(["dj-*"])
    assert not isinstance(union, FittingSelection)
    with pytest.raises(RefusalError, match="dj-2026-10/dj"):
        union.for_fitting(REGISTER)


def test_a_refusal_carries_its_problems_and_how_many_clips_are_at_fault(data):
    with pytest.raises(RefusalError) as e:
        data.select().for_gate({**REGISTER, "dj-corpus": "deny"})
    r = e.value.refusal
    assert r.clips == 4 and not r.synthetic_only  # 2 synthetic clips of smoke, 2 dj clips
    with pytest.raises(RefusalError) as e:
        data.select(["smoke"]).for_gate(REGISTER)
    assert e.value.refusal.synthetic_only and e.value.refusal.clips == 2


def test_the_default_register_is_the_checkouts_own(data):
    data.select(["aishell3"], splits=["calib"]).for_fitting()  # aishell-3 is allow in data-register.csv
    with pytest.raises(RefusalError, match="synthetic-world' is 'deny'"):
        data.select(["smoke"]).for_fitting()


def test_the_register_may_be_one_read_from_a_file(data, tmp_path):
    path = tmp_path / "register.csv"
    path.write_text("id,shipped_weights_training\naishell-3,deny\n", encoding="utf-8")
    with pytest.raises(RefusalError, match="aishell-3' is 'deny'"):
        data.select(["aishell3"], splits=["calib"]).for_fitting(clearance.read_register(str(path)))


# ---- gates ----------------------------------------------------------------------------------


def test_a_gate_on_recordings_is_allowed(data):
    selection = data.select(kinds=["recorded"], splits=["gate"], sets=["gate"])
    checked = selection.for_gate(REGISTER)
    assert isinstance(checked, GateSelection) and checked.items == selection.items


def test_a_gate_on_public_heldout_speakers_is_allowed(data):
    data.select(["aishell3"], splits=["heldout"]).for_gate(REGISTER)


def test_a_gate_on_a_synthetic_corpus_is_refused_naming_the_corpus(data):
    with pytest.raises(RefusalError) as e:
        data.select(["smoke"]).for_gate(REGISTER)
    text = str(e.value)
    assert text.startswith("refusing to grade a gate on this selection:")
    assert "smoke: synthetic corpus (2 clips); a gate is measured on real recordings" in text
    assert "deny" not in text  # one reason per corpus: the synthetic one


def test_a_gate_refuses_synthetic_clips_hidden_in_a_recorded_corpus(tmp_path):
    clips = speaker_clips("dj", "dj-corpus") + speaker_clips("dj", "dj-corpus", n=1, set="synthetic")
    add_corpus(tmp_path, "mixed", kind="recorded", source="dj-corpus", speakers=[speaker("dj")], clips=clips)
    with pytest.raises(RefusalError, match=r"mixed: synthetic clips \(1 clip, speakers mixed/dj\)"):
        DataRoot(tmp_path).select().for_gate(REGISTER)


@pytest.mark.parametrize(
    "source,why",
    [("latic", "is 'verify' in the data register, not 'allow'"), ("not-a-source", "is not in the data register")],
)
def test_a_gate_on_a_source_the_register_does_not_clear_is_refused(tmp_path, source, why):
    add_corpus(tmp_path, "l2", kind="recorded", source=source, speakers=[speaker("s")], clips=speaker_clips("s", source))
    with pytest.raises(RefusalError, match=rf"l2: source '{source}' {why} \(2 clips\)"):
        DataRoot(tmp_path).select().for_gate(REGISTER)


def test_a_gate_is_refused_for_every_corpus_at_fault_at_once(data):
    with pytest.raises(RefusalError) as e:
        data.select().for_gate({**REGISTER, "dj-corpus": "deny"})
    text = str(e.value)
    assert "smoke: synthetic corpus" in text and "dj-2026-10: source 'dj-corpus' is 'deny'" in text
    assert "volunteers-2026-10" not in text and "aishell3" not in text


def test_a_gate_does_not_refuse_gate_or_calib_speakers_as_such(data):
    # the speaker split is a fitting rule; what a gate may run on is the gate file's selection
    data.select(["aishell3"]).for_gate(REGISTER)


def test_the_default_register_clears_the_dj_corpus_and_refuses_synthetic_world(data):
    data.select(["dj-*"]).for_gate()
    with pytest.raises(RefusalError, match="smoke: synthetic corpus"):
        data.select(["smoke"]).for_gate()


def test_a_refusal_is_a_value_error_with_no_clips_returned(data):
    with pytest.raises(ValueError):
        data.select(["smoke"]).for_gate(REGISTER)
