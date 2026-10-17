"""`--select CORPUS_GLOB[:SPLIT[,SPLIT]]`: parsing, composing across corpora, and what is refused
(a malformed selector, a corpus that is not there, a selector that selects nothing). Tmp data roots
of manifest rows only (registry_support); no audio."""

from __future__ import annotations

import pytest
from registry_support import CALIB, DEV, HELDOUT, build_composed_root

from tonekit_harness.registry import DataRoot, SelectionError
from tonekit_harness.registry.runs import accent_summary, describe, selection_from
from tonekit_harness.registry.selectors import Selector, compose, parse_selector


@pytest.fixture
def data(tmp_path):
    return DataRoot(build_composed_root(tmp_path))


# ---- syntax -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,corpora,splits",
    [
        ("aishell3", "aishell3", None),
        ("volunteers-*", "volunteers-*", None),
        ("aishell3:calib", "aishell3", ("calib",)),
        ("aishell3:calib,dev", "aishell3", ("calib", "dev")),
        (" aishell3 : calib , dev ", "aishell3", ("calib", "dev")),
        ("aishell3:dev,dev", "aishell3", ("dev",)),
    ],
)
def test_a_selector_is_a_corpus_id_or_glob_and_optional_splits(text, corpora, splits):
    assert parse_selector(text) == Selector(text, corpora, splits)


@pytest.mark.parametrize(
    "text,why",
    [
        ("", "no corpus id or glob"),
        (":calib", "no corpus id or glob"),
        ("aishell3:", "an empty split"),
        ("aishell3:calib,", "an empty split"),
        ("aishell3:train", "unknown split train (known: gate, dev, calib, heldout)"),
        ("aishell3:calib,Gate", "unknown split Gate"),
    ],
)
def test_a_malformed_selector_says_what_is_wrong(text, why):
    with pytest.raises(SelectionError) as e:
        parse_selector(text)
    assert str(e.value).startswith(f"--select {text!r}: ") and why in str(e.value)


# ---- composing ----------------------------------------------------------------------------------


def test_selectors_compose_across_corpora_with_qualified_speakers(data):
    selection = compose(data, [parse_selector("aishell3:calib"), parse_selector("volunteers-*")])
    assert list(selection.corpora) == ["aishell3", "volunteers-2026-10"]
    assert list(selection.speakers) == [f"aishell3/{CALIB}", "volunteers-2026-10/v-k7q2md", "volunteers-2026-10/v-abcde2"]
    clips = selection.grading_clips()
    assert clips[0].id == f"aishell3/{CALIB}-gate-0" and clips[0].speaker == f"aishell3/{CALIB}"
    assert clips[0].path == f"aishell3/audio/{CALIB}/{CALIB}-gate-0.wav"  # resolved per corpus
    assert (selection.audio_root / clips[-1].path) == data.corpora_dir / "volunteers-2026-10" / "audio" / "v-abcde2" / "v-abcde2-register-0.wav"


def test_without_splits_a_selector_takes_the_commands_default(data):
    every = compose(data, [parse_selector("aishell3")])
    assert {s.split for s in every.speakers.values()} == {"calib", "dev", "heldout"}
    calib = compose(data, [parse_selector("aishell3")], default_splits=("calib",))
    assert list(calib.speakers) == [f"aishell3/{CALIB}"]
    explicit = compose(data, [parse_selector("aishell3:dev,heldout")], default_splits=("calib",))
    assert list(explicit.speakers) == [f"aishell3/{DEV}", f"aishell3/{HELDOUT}"]


def test_overlapping_selectors_take_each_clip_once(data):
    selection = compose(data, [parse_selector("aishell3:calib"), parse_selector("aishell*")])
    assert len(selection) == 6 and len({i.key for i in selection.items}) == 6


def test_a_corpus_id_that_is_not_there_is_refused(data):
    with pytest.raises(SelectionError, match=r"select: no corpus 'aishell-3' \(corpora: aishell3, dj-2026-10, smoke"):
        compose(data, [parse_selector("aishell-3")])


def test_a_glob_that_matches_no_corpus_is_refused_when_it_is_a_selector(data):
    with pytest.raises(SelectionError) as e:
        compose(data, [parse_selector("aishell3"), parse_selector("thchs*:calib")])
    assert str(e.value) == (
        "--select 'thchs*:calib' selects no clips: no corpus matches the glob 'thchs*' "
        "(corpora: aishell3, dj-2026-10, smoke, volunteers-2026-10)"
    )


def test_a_selector_whose_split_has_no_speaker_is_refused(data):
    with pytest.raises(SelectionError) as e:
        compose(data, [parse_selector("volunteers-*:calib")])
    assert str(e.value) == (
        "--select 'volunteers-*:calib' selects no clips: volunteers-2026-10 has no clips of a speaker in split calib"
    )


def test_no_selector_is_refused(data):
    with pytest.raises(SelectionError, match="no --select given"):
        compose(data, [])


def test_speakers_keep_only_those_named_and_a_speaker_not_selected_is_an_error(data):
    sel = selection_from([parse_selector("volunteers-*")], data.path, None, default_splits=None,
                         speakers=["volunteers-2026-10/v-abcde2"])  # fmt: skip
    assert list(sel.speakers) == ["volunteers-2026-10/v-abcde2"]
    with pytest.raises(SelectionError, match=r"speaker\(s\) v-abcde2 not in the selection \(speakers: volunteers-2026-10/v-k7q2md"):
        selection_from([parse_selector("volunteers-*")], data.path, None, default_splits=None, speakers=["v-abcde2"])


def test_a_report_describes_each_corpus_and_the_accents(data):
    selection = compose(data, [parse_selector("aishell3:calib,dev"), parse_selector("volunteers-*")])
    assert describe(selection) == (
        "aishell3 (public, aishell-3): 4 clips of 2 speakers (calib 2, dev 2); "
        "volunteers-2026-10 (recorded, volunteer-corpus): 6 clips of 2 speakers (gate 6)"
    )
    assert accent_summary(selection.accents()) == "cmn-TW 1 speaker, cmn-standard 3 speakers"
