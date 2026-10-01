"""registry.DataRoot and corpus loading: finding corpora, joining manifest rows to speakers, and
errors that name the file and line."""

from __future__ import annotations

import pytest
from registry_support import add_corpus, build_composed_root, clip, speaker, write_corpus_file

from tonekit_harness.contracts.registry import RegistryError
from tonekit_harness.registry import DataRoot
from tonekit_harness.registry.rows import MAX_PROBLEMS_SHOWN

V = "volunteer-corpus"


@pytest.fixture
def data(tmp_path):
    return DataRoot(build_composed_root(tmp_path))


def one_corpus(tmp_path, clips, speakers=None, **kw):
    """A root holding `c1` (recorded, volunteer-corpus) with a single speaker `dj` by default."""
    add_corpus(tmp_path, "c1", kind="recorded", source=V, speakers=speakers or [speaker("dj")], clips=clips, **kw)
    return DataRoot(tmp_path)


# ---- where the root is ----------------------------------------------------------------------


def test_a_root_given_a_path_uses_it(tmp_path):
    assert DataRoot(tmp_path).path == tmp_path


def test_the_environment_names_the_root_when_no_path_is_given(monkeypatch, tmp_path):
    monkeypatch.setenv("TONEKIT_DATA", str(tmp_path / "env"))
    assert DataRoot().path == tmp_path / "env"
    assert DataRoot(tmp_path / "flag").path == tmp_path / "flag"


def test_the_default_root_is_tonekit_data_in_the_home_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TONEKIT_DATA", raising=False)
    assert DataRoot().path == tmp_path / "tonekit-data"


def test_nothing_is_created_by_asking_for_a_root(tmp_path):
    root = DataRoot(tmp_path / "nowhere")
    assert root.corpus_ids() == []
    assert not (tmp_path / "nowhere").exists()


# ---- listing and loading --------------------------------------------------------------------


def test_corpus_ids_are_the_corpus_directories_sorted(data):
    (data.corpora_dir / "a-file.txt").write_text("not a corpus", encoding="utf-8")
    assert data.corpus_ids() == ["aishell3", "dj-2026-10", "smoke", "volunteers-2026-10"]


def test_a_corpus_loads_with_its_meta_and_speakers(data):
    corpus = data.corpus("volunteers-2026-10")
    assert (corpus.meta.kind, corpus.meta.source, corpus.meta.lect) == ("recorded", V, "cmn")
    assert list(corpus.speakers) == ["v-k7q2md", "v-abcde2"]
    assert corpus.speakers["v-k7q2md"].accent == "cmn-TW"


def test_clips_are_joined_to_their_speaker_and_corpus(data):
    corpus = data.corpus("volunteers-2026-10")
    first = corpus.clips[0]
    assert first.clip.id == "v-k7q2md-gate-0" and first.speaker.id == "v-k7q2md"
    assert first.speaker.grew_up_hearing == "taiwan" and first.corpus.id == "volunteers-2026-10"
    assert len(corpus.clips) == 6  # per volunteer: two gate clips and a register clip
    assert [c.clip.id for c in corpus.clips if c.speaker.id == "v-abcde2"][:1] == ["v-abcde2-gate-0"]


def test_audio_paths_are_relative_to_the_manifest_directory(data):
    corpus = data.corpus("dj-2026-10")
    assert corpus.clips[0].audio_path == corpus.directory / "audio" / "dj" / "dj-gate-0.wav"


def test_a_manifest_in_a_subdirectory_makes_its_clip_paths_relative_to_it(tmp_path):
    root = one_corpus(tmp_path, [clip("c", "dj", source=V, path="wavs/c.wav")], manifest="meta/manifest.jsonl")
    corpus = root.corpus("c1")
    assert corpus.manifest_path == tmp_path / "corpora" / "c1" / "meta" / "manifest.jsonl"
    assert corpus.clips[0].audio_path == tmp_path / "corpora" / "c1" / "meta" / "wavs" / "c.wav"


def test_a_corpus_may_have_no_clips_yet(tmp_path):
    root = one_corpus(tmp_path, [])
    assert root.corpus("c1").clips == ()


def test_the_manifest_is_only_read_when_its_clips_are_asked_for(tmp_path):
    root = one_corpus(tmp_path, None)  # corpus.toml but no manifest at all
    assert root.corpus("c1").meta.id == "c1"
    with pytest.raises(RegistryError, match="no such manifest"):
        root.corpus("c1").clips  # noqa: B018


def test_a_clip_may_carry_the_deck_fields(tmp_path):
    c = clip("c", "dj", source=V).model_copy(update={"card": "g01-c", "deck": "s05-v1", "take": 2, "context": "phrase"})
    [loaded] = one_corpus(tmp_path, [c]).corpus("c1").clips
    assert (loaded.clip.card, loaded.clip.deck, loaded.clip.take, loaded.clip.context) == ("g01-c", "s05-v1", 2, "phrase")


# ---- corpus.toml errors ---------------------------------------------------------------------


def test_an_unknown_corpus_lists_the_ones_there_are(data):
    with pytest.raises(RegistryError, match=r"nope: no such corpus \(have: aishell3, dj-2026-10, smoke, volunteers-2026-10\)"):
        data.corpus("nope")


def test_a_corpus_id_cannot_leave_the_corpora_directory(data):
    for bad in ("..", "../corpora", "a/b", ""):
        with pytest.raises(RegistryError, match="no such corpus"):
            data.corpus(bad)


def test_a_directory_without_corpus_toml_names_the_missing_file(tmp_path):
    (tmp_path / "corpora" / "half").mkdir(parents=True)
    with pytest.raises(RegistryError, match=r"half/corpus\.toml: no corpus\.toml"):
        DataRoot(tmp_path).corpus("half")


def test_invalid_toml_names_the_file(tmp_path):
    (tmp_path / "corpora" / "c1").mkdir(parents=True)
    (tmp_path / "corpora" / "c1" / "corpus.toml").write_text("[corpus\n", encoding="utf-8")
    with pytest.raises(RegistryError, match=r"c1/corpus\.toml: invalid TOML"):
        DataRoot(tmp_path).corpus("c1")


def test_an_invalid_field_names_the_file_and_the_speaker(tmp_path):
    add_corpus(tmp_path, "c1", kind="recorded", source=V, speakers=[speaker("dj", split="train")], clips=[])
    with pytest.raises(RegistryError, match=r"c1/corpus\.toml.*\n.*speaker 'dj'\.split"):
        DataRoot(tmp_path).corpus("c1")


def test_a_corpus_file_that_is_not_utf8_names_the_file(tmp_path):
    (tmp_path / "corpora" / "c1").mkdir(parents=True)
    (tmp_path / "corpora" / "c1" / "corpus.toml").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(RegistryError, match=r"c1/corpus\.toml: cannot read the corpus file"):
        DataRoot(tmp_path).corpus("c1")


def test_the_corpus_id_must_be_the_directory_name(tmp_path):
    write_corpus_file(tmp_path / "corpora" / "c1", "other", kind="recorded", source=V, speakers=[])
    with pytest.raises(RegistryError, match=r"c1/corpus\.toml: corpus id 'other' does not match its directory name 'c1'"):
        DataRoot(tmp_path).corpus("c1")


# ---- manifest errors ------------------------------------------------------------------------


def test_a_missing_manifest_is_named_with_the_corpus_that_asked_for_it(tmp_path):
    root = one_corpus(tmp_path, None, manifest="rows.jsonl")
    with pytest.raises(RegistryError, match=r"c1/rows\.jsonl: no such manifest \(corpus 'c1' names manifest = 'rows\.jsonl'\)"):
        root.corpus("c1").clips  # noqa: B018


def test_a_bad_manifest_row_names_the_file_and_line_skipping_blank_lines(tmp_path):
    root = one_corpus(tmp_path, [clip("a", "dj", source=V)])
    manifest = tmp_path / "corpora" / "c1" / "manifest.jsonl"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "\n\n{oops\n", encoding="utf-8")
    with pytest.raises(RegistryError, match=r"c1/manifest\.jsonl:4: invalid JSON"):
        root.corpus("c1").clips  # noqa: B018


def test_an_invalid_clip_row_names_the_line(tmp_path):
    root = one_corpus(tmp_path, [clip("a", "dj", source=V)])
    manifest = tmp_path / "corpora" / "c1" / "manifest.jsonl"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace('"set":"gate"', '"set":"nope"'), encoding="utf-8")
    with pytest.raises(RegistryError, match=r"(?s)c1/manifest\.jsonl:1:.*set"):
        root.corpus("c1").clips  # noqa: B018


def test_a_manifest_that_is_not_utf8_names_the_file(tmp_path):
    root = one_corpus(tmp_path, [])
    (tmp_path / "corpora" / "c1" / "manifest.jsonl").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(RegistryError, match=r"c1/manifest\.jsonl: cannot read the manifest"):
        root.corpus("c1").clips  # noqa: B018


def test_a_clip_of_an_unknown_speaker_names_the_line_and_the_speaker(tmp_path):
    root = one_corpus(tmp_path, [clip("a", "dj", source=V), clip("b", "ghost", source=V)])
    with pytest.raises(RegistryError, match=r"corpus 'c1': invalid manifest\n  .*c1/manifest\.jsonl:2: clip 'b': speaker 'ghost' is not a \[\[speaker\]\]"):
        root.corpus("c1").clips  # noqa: B018


def test_a_repeated_clip_id_names_both_lines(tmp_path):
    root = one_corpus(tmp_path, [clip("a", "dj", source=V), clip("b", "dj", source=V), clip("a", "dj", source=V)])
    with pytest.raises(RegistryError, match=r"manifest\.jsonl:3: clip id 'a' is used twice \(first on line 1\)"):
        root.corpus("c1").clips  # noqa: B018


@pytest.mark.parametrize("path", ["/etc/hosts", "../other/a.wav", "audio/../../a.wav"])
def test_a_clip_path_must_stay_inside_the_corpus(tmp_path, path):
    root = one_corpus(tmp_path, [clip("a", "dj", source=V, path=path)])
    with pytest.raises(RegistryError, match=r"manifest\.jsonl:1: clip 'a': path .* must be relative, with no '\.\.'"):
        root.corpus("c1").clips  # noqa: B018


def test_a_clip_source_must_be_the_corpus_source(tmp_path):
    root = one_corpus(tmp_path, [clip("a", "dj", source="dj-corpus")])
    with pytest.raises(RegistryError, match=r"manifest\.jsonl:1: clip 'a': source 'dj-corpus' is not the corpus's source 'volunteer-corpus'"):
        root.corpus("c1").clips  # noqa: B018


def test_every_problem_is_listed_up_to_a_limit(tmp_path):
    n = MAX_PROBLEMS_SHOWN + 5
    root = one_corpus(tmp_path, [clip(f"c{i}", "ghost", source=V) for i in range(n)])
    with pytest.raises(RegistryError) as e:
        root.corpus("c1").clips  # noqa: B018
    text = str(e.value)
    assert text.count("speaker 'ghost'") == MAX_PROBLEMS_SHOWN
    assert "and 5 more problems" in text and "manifest.jsonl:1:" in text
