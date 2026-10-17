"""Selecting across corpora: globs, kinds, splits, sets, composition and the grading view."""

from __future__ import annotations

import pytest
from registry_support import CALIB, DEV, add_corpus, build_composed_root, clip, speaker, speaker_clips

from tonekit_harness.contracts.registry import RegistryError
from tonekit_harness.registry import DataRoot, SelectionError


@pytest.fixture
def data(tmp_path):
    return DataRoot(build_composed_root(tmp_path))


def ids(selection):
    return [i.qualified_id for i in selection.items]


def corpora_of(selection):
    return list(selection.corpora)


# ---- globs and ids --------------------------------------------------------------------------


def test_selecting_everything_is_a_union_over_every_corpus_in_id_order(data):
    everything = data.select()
    assert corpora_of(everything) == ["aishell3", "dj-2026-10", "smoke", "volunteers-2026-10"]
    assert len(everything) == 6 + 2 + 6 + 2  # volunteers, dj, aishell3, smoke


def test_an_exact_id_selects_that_corpus(data):
    assert corpora_of(data.select(["dj-2026-10"])) == ["dj-2026-10"]


def test_a_glob_selects_every_match(data):
    assert corpora_of(data.select(["*-2026-10"])) == ["dj-2026-10", "volunteers-2026-10"]
    assert corpora_of(data.select(["volunteers-*"])) == ["volunteers-2026-10"]
    assert corpora_of(data.select(["s?oke"])) == ["smoke"]


def test_several_patterns_are_a_union_without_repeats(data):
    both = data.select(["volunteers-*", "*-2026-10", "dj-2026-10"])
    assert corpora_of(both) == ["dj-2026-10", "volunteers-2026-10"]
    assert len(both) == len(data.select(["*-2026-10"]))


def test_a_mistyped_id_is_an_error_not_an_empty_selection(data):
    with pytest.raises(SelectionError, match=r"no corpus 'volunteers-2026-11' \(corpora: aishell3, dj-2026-10"):
        data.select(["volunteers-2026-11"])


def test_a_glob_that_matches_nothing_selects_nothing(data):
    assert corpora_of(data.select(["dj-*", "later-*"])) == ["dj-2026-10"]
    assert len(data.select(["later-*"])) == 0


def test_an_empty_data_root_selects_nothing(tmp_path):
    assert len(DataRoot(tmp_path).select()) == 0


# ---- kinds, splits, sets --------------------------------------------------------------------


def test_kinds_filter_the_corpora(data):
    assert corpora_of(data.select(kinds=["recorded"])) == ["dj-2026-10", "volunteers-2026-10"]
    assert corpora_of(data.select(kinds=["public", "synthetic"])) == ["aishell3", "smoke"]


def test_splits_filter_the_speakers(data):
    gate = data.select(splits=["gate"])
    assert set(gate.speakers) == {"dj-2026-10/dj", "volunteers-2026-10/v-k7q2md", "volunteers-2026-10/v-abcde2"}
    calib = data.select(["aishell3"], splits=["calib", "dev"])
    assert set(calib.speakers) == {f"aishell3/{CALIB}", f"aishell3/{DEV}"}


def test_sets_filter_the_clips(data):
    register = data.select(["volunteers-*"], sets=["register"])
    assert ids(register) == ["volunteers-2026-10/v-k7q2md-register-0", "volunteers-2026-10/v-abcde2-register-0"]
    assert corpora_of(data.select(sets=["synthetic"])) == ["smoke"]


def test_the_filters_combine(data):
    selection = data.select(["*"], kinds=["recorded"], splits=["gate"], sets=["gate"])
    assert len(selection) == 2 + 2 + 2  # v-k7q2md, v-abcde2 and dj, two gate clips each
    assert all(i.clip.set == "gate" and i.speaker.split == "gate" for i in selection.items)


def test_a_gate_files_select_table_is_the_argument_list(data):
    from tonekit_harness.contracts.gate import Select

    s = Select(corpora=["*"], kinds=["recorded"], splits=["gate"], sets=["gate"])
    assert ids(data.select(**s.model_dump())) == ids(data.select(["*"], kinds=["recorded"], splits=["gate"], sets=["gate"]))


@pytest.mark.parametrize("name,value", [("kinds", []), ("splits", []), ("sets", []), ("corpora", [])])
def test_an_empty_list_is_an_error_not_everything_or_nothing(data, name, value):
    with pytest.raises(SelectionError, match=f"{name} is empty"):
        data.select(**{name: value})


@pytest.mark.parametrize("name,value", [("kinds", ["live"]), ("splits", ["train"]), ("sets", ["diag"]), ("splits", ["gate", "Heldout"])])
def test_an_unknown_value_is_an_error(data, name, value):
    with pytest.raises(SelectionError, match=f"unknown {name}"):
        data.select(**{name: value})


def test_a_bare_string_is_an_error(data):
    with pytest.raises(SelectionError, match="must be a list"):
        data.select("dj-2026-10")


def test_a_selection_only_names_corpora_that_gave_it_clips(data):
    assert corpora_of(data.select(splits=["heldout"])) == ["aishell3"]


# ---- what a selection reads -----------------------------------------------------------------


def test_a_corpus_with_no_speaker_in_the_split_does_not_have_its_manifest_read(data):
    (data.corpora_dir / "aishell3" / "manifest.jsonl").write_text("{broken\n", encoding="utf-8")
    assert len(data.select(splits=["gate"])) == 6 + 2  # the volunteers' and dj's gate speakers
    with pytest.raises(RegistryError, match=r"aishell3/manifest\.jsonl:1: invalid JSON"):
        data.select(splits=["calib"])


def test_a_corpus_that_cannot_be_loaded_stops_a_selection_that_needs_it(data):
    (data.corpora_dir / "dj-2026-10" / "corpus.toml").unlink()
    with pytest.raises(RegistryError, match=r"dj-2026-10/corpus\.toml: no corpus\.toml"):
        data.select()
    assert len(data.select(["volunteers-*"])) == 6  # a corpus the patterns do not match is not read


# ---- speakers across corpora ----------------------------------------------------------------


def test_speaker_ids_are_qualified_by_corpus(tmp_path):
    root = tmp_path
    for corpus in ("lab-a", "lab-b"):
        add_corpus(root, corpus, kind="recorded", source="dj-corpus", speakers=[speaker("dj")],
                   clips=speaker_clips("dj", "dj-corpus"))  # fmt: skip
    selection = DataRoot(root).select()
    assert list(selection.speakers) == ["lab-a/dj", "lab-b/dj"]
    assert ids(selection) == ["lab-a/dj-gate-0", "lab-a/dj-gate-1", "lab-b/dj-gate-0", "lab-b/dj-gate-1"]


def test_a_selection_knows_its_corpora_and_speakers(data):
    selection = data.select(["volunteers-*"], splits=["gate"])
    assert selection.corpora["volunteers-2026-10"].source == "volunteer-corpus"
    assert selection.speakers["volunteers-2026-10/v-k7q2md"].grew_up_hearing == "taiwan"
    assert [c.id for c in selection.clips][:2] == ["v-k7q2md-gate-0", "v-k7q2md-gate-1"]


# ---- composition ----------------------------------------------------------------------------


def test_public_calib_composes_with_volunteer_gate(data):
    fit = data.select(kinds=["public"], splits=["calib"])
    gate = data.select(kinds=["recorded"], splits=["gate"], sets=["gate"])
    both = fit | gate
    assert corpora_of(both) == ["aishell3", "dj-2026-10", "volunteers-2026-10"]
    assert set(both.speakers) == {f"aishell3/{CALIB}", "dj-2026-10/dj", "volunteers-2026-10/v-k7q2md", "volunteers-2026-10/v-abcde2"}
    assert len(both) == len(fit) + len(gate)


def test_a_union_keeps_a_clip_once(data):
    volunteers = data.select(["volunteers-*"], sets=["gate"])
    assert len(volunteers | volunteers) == len(volunteers)
    assert len(volunteers | data.select(["volunteers-*"])) == len(data.select(["volunteers-*"]))


def test_selections_from_two_roots_do_not_compose(tmp_path):
    a = DataRoot(build_composed_root(tmp_path / "a")).select()
    b = DataRoot(build_composed_root(tmp_path / "b")).select()
    with pytest.raises(ValueError, match="different data roots"):
        a | b


# ---- the grading view -----------------------------------------------------------------------


def test_grading_clips_qualify_ids_and_point_at_the_audio_from_the_corpora_directory(data):
    selection = data.select(["dj-2026-10"])
    first = selection.grading_clips()[0]
    assert (first.id, first.speaker) == ("dj-2026-10/dj-gate-0", "dj-2026-10/dj")
    assert first.path == "dj-2026-10/audio/dj/dj-gate-0.wav"
    assert selection.audio_root == data.corpora_dir
    assert selection.clips[0].id == "dj-gate-0"  # the manifest rows themselves are untouched
    assert selection.clips[0].path == "audio/dj/dj-gate-0.wav"


def test_grading_clips_keep_everything_else_of_the_row(data):
    selection = data.select(["volunteers-*"], sets=["register"])
    row, graded = selection.items[0], selection.grading_clips()[0]
    assert graded.model_dump(exclude={"id", "speaker", "path"}) == row.clip.model_dump(exclude={"id", "speaker", "path"})


def test_the_clips_of_two_corpora_with_the_same_ids_can_be_graded_together(tmp_path):
    for corpus in ("lab-a", "lab-b"):
        add_corpus(tmp_path, corpus, kind="recorded", source="dj-corpus", speakers=[speaker("dj")],
                   clips=[clip("g1", "dj", source="dj-corpus")])  # fmt: skip
    graded = DataRoot(tmp_path).select().grading_clips()
    assert len({c.id for c in graded}) == 2 and len({c.speaker for c in graded}) == 2
