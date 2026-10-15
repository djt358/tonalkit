"""`intake_bundle`: what it writes under the data root, and that a refusal or a failure writes
nothing."""

from __future__ import annotations

import json
import tomllib

import pytest
from bundle_support import session_dict
from intake_support import SMALL, entries, kit_bundle, kit_session, options, tree

from tonekit_harness import clearance, manifest
from tonekit_harness.contracts.bundle import Bundle, read_bundle
from tonekit_harness.contracts.registry import load_corpus_file
from tonekit_harness.intake import run
from tonekit_harness.intake.errors import IntakeError
from tonekit_harness.intake.run import intake_bundle

CORPUS = "corpora/volunteers-s05-v1"


@pytest.fixture
def root(tmp_path):
    return tmp_path / "data"


def test_a_zip_becomes_audio_a_session_copy_rows_and_a_speaker(tmp_path, root):
    bundle = kit_bundle(tmp_path / "in")
    result = intake_bundle(bundle, options(root))
    files = tree(root)
    audio = {f"{CORPUS}/audio/K7Q2MD/{c}.wav" for c in SMALL}
    assert set(files) == audio | {f"{CORPUS}/{n}" for n in ("corpus.toml", "manifest.jsonl", "sessions/K7Q2MD.json")}
    read = read_bundle(bundle)
    for card in SMALL:
        assert files[f"{CORPUS}/audio/K7Q2MD/{card}.wav"] == read.clip_bytes(card)  # byte for byte
    assert files[f"{CORPUS}/sessions/K7Q2MD.json"] == read.session_bytes()
    assert result.created and result.corpus_id == "volunteers-s05-v1" and result.speaker.id == "v-k7q2md"
    assert result.per_set == {"register": 1, "gate": 4, "diag_minimal": 1}


def test_a_folder_gives_the_same_rows_and_speaker_as_its_zip(tmp_path):
    zipped = intake_bundle(kit_bundle(tmp_path / "a"), options(tmp_path / "d1"))
    folded = intake_bundle(kit_bundle(tmp_path / "b", folder=True), options(tmp_path / "d2"))
    assert manifest.load(zipped.manifest) == manifest.load(folded.manifest)
    assert (tmp_path / "d1" / CORPUS / "corpus.toml").read_text() == (tmp_path / "d2" / CORPUS / "corpus.toml").read_text()


def test_the_new_corpus_file_is_recorded_volunteer_corpus_with_the_sessions_speaker(tmp_path, root):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    corpus = load_corpus_file(root / CORPUS / "corpus.toml")
    assert corpus.corpus.model_dump() == {
        "id": "volunteers-s05-v1", "source": "volunteer-corpus", "kind": "recorded", "lect": "cmn",
        "manifest": "manifest.jsonl",
    }  # fmt: skip
    [speaker] = corpus.speaker
    assert speaker.model_dump() == {
        "id": "v-k7q2md", "background": "native", "grew_up_hearing": "taiwan", "accent": None,
        "split": "gate", "sessions": ["K7Q2MD"],
    }  # fmt: skip
    assert "accent" not in tomllib.loads((root / CORPUS / "corpus.toml").read_text())["speaker"][0]


def test_prefer_not_answers_are_kept_as_given(tmp_path, root):
    session = kit_session("ABCDEF", ["r01"])
    session["speaker"] |= {"background": "prefer_not", "grew_up_hearing": "prefer_not"}
    intake_bundle(kit_bundle(tmp_path / "in", "ABCDEF", session=session), options(root))
    [speaker] = load_corpus_file(root / CORPUS / "corpus.toml").speaker
    assert (speaker.background, speaker.grew_up_hearing) == ("prefer_not", "prefer_not")


def test_rows_load_with_the_data_register_and_carry_the_corpus_source(tmp_path, root):
    result = intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    clips = manifest.load(result.manifest, register=clearance.read_register(None))
    assert [c.id for c in clips] == ["K7Q2MD-r01", "K7Q2MD-g01-c", "K7Q2MD-g01-e", "K7Q2MD-g02-c",
                                     "K7Q2MD-g02-e", "K7Q2MD-m01-a"]  # fmt: skip
    assert {c.source for c in clips} == {"volunteer-corpus"}
    assert all((result.manifest.parent / c.path).is_file() for c in clips)


def test_a_second_session_is_appended_and_adds_its_speaker(tmp_path, root):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    first = (root / CORPUS / "manifest.jsonl").read_bytes()
    result = intake_bundle(kit_bundle(tmp_path / "in", "ABCDEF", ["r01", "x01"]), options(root))
    after = (root / CORPUS / "manifest.jsonl").read_bytes()
    assert not result.created and after.startswith(first)
    assert [json.loads(line)["id"] for line in after[len(first):].splitlines()] == ["ABCDEF-r01", "ABCDEF-x01"]
    assert [s.id for s in load_corpus_file(root / CORPUS / "corpus.toml").speaker] == ["v-k7q2md", "v-abcdef"]


def test_the_same_session_again_is_refused_in_any_corpus_and_nothing_changes(tmp_path, root):
    bundle = kit_bundle(tmp_path / "in")
    intake_bundle(bundle, options(root))
    before = tree(root)
    with pytest.raises(IntakeError, match="already in corpus volunteers-s05-v1.*tkh purge --session K7Q2MD"):
        intake_bundle(bundle, options(root))
    with pytest.raises(IntakeError, match="already in corpus volunteers-s05-v1"):
        intake_bundle(kit_bundle(tmp_path / "again", folder=True), options(root, corpus_id="elsewhere"))
    assert tree(root) == before


def test_an_explicit_corpus_id_is_used(tmp_path, root):
    result = intake_bundle(kit_bundle(tmp_path / "in"), options(root, corpus_id="dj-trial"))
    assert result.corpus_id == "dj-trial" and (root / "corpora/dj-trial/corpus.toml").is_file()


def test_a_source_not_in_the_register_is_refused(tmp_path, root):
    with pytest.raises(IntakeError, match="'nope' is not an id in data-register.csv"):
        intake_bundle(kit_bundle(tmp_path / "in"), options(root, source="nope"))
    assert entries(root) == []


def test_an_existing_corpus_keeps_its_source_and_kind(tmp_path, root):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    with pytest.raises(IntakeError, match="has source 'volunteer-corpus', not --source 'dj-corpus'"):
        intake_bundle(kit_bundle(tmp_path / "in", "ABCDEF"), options(root, source="dj-corpus"))
    (root / "corpora/pub").mkdir()
    (root / "corpora/pub/corpus.toml").write_text(
        '[corpus]\nid = "pub"\nsource = "aishell-3"\nkind = "public"\nlect = "cmn"\n', encoding="utf-8"
    )
    with pytest.raises(IntakeError, match="is public; kit sessions go into a recorded corpus"):
        intake_bundle(kit_bundle(tmp_path / "in", "ABCDEF"), options(root, corpus_id="pub"))


def test_a_session_with_nothing_to_keep_is_refused(tmp_path, root):
    session = kit_session("ABCDEF", ["g01-c"], skipped=["g01-e"])
    with pytest.raises(IntakeError, match="no clip to keep"):
        intake_bundle(kit_bundle(tmp_path / "in", "ABCDEF", session=session), options(root))
    assert entries(root) == []


def test_a_corpus_directory_without_a_corpus_file_is_refused(tmp_path, root):
    (root / CORPUS).mkdir(parents=True)
    (root / CORPUS / "something").write_text("x", encoding="utf-8")
    with pytest.raises(IntakeError, match="exists but has no corpus.toml"):
        intake_bundle(kit_bundle(tmp_path / "in"), options(root))


def test_an_invalid_bundle_is_refused_with_the_contracts_reasons(tmp_path, root):
    bad = kit_bundle(tmp_path / "in", session=session_dict(session="bad"))
    with pytest.raises(IntakeError, match="session.json is invalid"):
        intake_bundle(bad, options(root))
    assert entries(root) == []


def test_a_staging_area_left_by_a_killed_intake_is_cleared(tmp_path, root):
    leftover = root / "corpora" / ".intake-K7Q2MD-1"
    leftover.mkdir(parents=True)
    (leftover / "x.wav").write_bytes(b"old")
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    assert not leftover.exists()
    assert not [p for p in (root / "corpora").iterdir() if p.name.startswith(".")]


# ---- a failure leaves nothing half written --------------------------------------------------


def test_a_failure_while_staging_leaves_the_data_root_as_it_was(tmp_path, root, monkeypatch):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    before, listing = tree(root), entries(root)
    calls = {"n": 0}
    real = Bundle.clip_bytes

    def flaky(self, card):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real(self, card)

    monkeypatch.setattr(Bundle, "clip_bytes", flaky)
    with pytest.raises(OSError, match="disk full"):
        intake_bundle(kit_bundle(tmp_path / "in", "ABCDEF"), options(root))
    assert tree(root) == before and entries(root) == listing


def test_a_failure_at_the_last_step_of_moving_in_undoes_the_others(tmp_path, root, monkeypatch):
    intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    before, listing = tree(root), entries(root)

    class FailOnCorpusFile(run.Replace):
        def do(self):
            if self.dst.name == "corpus.toml":
                raise OSError("no space left")
            super().do()

    monkeypatch.setattr(run, "Replace", FailOnCorpusFile)
    with pytest.raises(OSError, match="no space left"):
        intake_bundle(kit_bundle(tmp_path / "in", "ABCDEF"), options(root))
    assert tree(root) == before and entries(root) == listing


def test_a_failure_moving_a_new_corpus_in_leaves_nothing(tmp_path, root, monkeypatch):
    def broken(src, dst):
        raise OSError("rename failed")

    monkeypatch.setattr(run, "move_dir_into_place", broken)
    with pytest.raises(OSError, match="rename failed"):
        intake_bundle(kit_bundle(tmp_path / "in"), options(root))
    assert entries(root) == ["corpora"]


def test_a_bundle_with_an_extra_field_is_refused_at_the_door(tmp_path, root):
    session = kit_session()
    session["speaker"]["email"] = "someone@example.invalid"
    with pytest.raises(IntakeError, match="email"):
        intake_bundle(kit_bundle(tmp_path / "in", session=session), options(root))
    assert entries(root) == []


def test_clip_paths_are_relative_to_a_manifest_in_a_subdirectory(tmp_path, root):
    corpus = root / "corpora" / "nested"
    corpus.mkdir(parents=True)
    (corpus / "corpus.toml").write_text(
        '[corpus]\nid = "nested"\nsource = "volunteer-corpus"\nkind = "recorded"\nlect = "cmn"\n'
        'manifest = "lists/manifest.jsonl"\n',
        encoding="utf-8",
    )
    result = intake_bundle(kit_bundle(tmp_path / "in"), options(root, corpus_id="nested"))
    assert result.manifest == corpus / "lists" / "manifest.jsonl"
    clips = manifest.load(result.manifest)
    assert clips[0].path == "../audio/K7Q2MD/r01.wav"
    assert all((result.manifest.parent / c.path).is_file() for c in clips)
