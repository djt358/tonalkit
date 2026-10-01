"""contracts.registry: data root, corpus.toml, speakers, splits, accents, the purge log
(contracts.md sections 3 and 6). Loading and format rules only."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tonekit_harness.contracts.lects import LectError
from tonekit_harness.contracts.registry import (
    CorpusFile,
    PurgeRecord,
    RegistryError,
    Speaker,
    corpus_dir,
    corpus_file_path,
    data_root,
    default_accent,
    default_split,
    hashed_split,
    inbox_dir,
    load_corpus_file,
    load_purge_log,
    purge_log_path,
    volunteer_speaker_id,
)

EXAMPLE = """\
[corpus]
id = "volunteers-2026-10"
source = "volunteer-corpus"
kind = "recorded"
lect = "cmn"
manifest = "manifest.jsonl"

[[speaker]]
id = "v-k7q2md"
background = "native"
grew_up_hearing = "taiwan"
accent = "cmn-TW"
split = "gate"
sessions = ["K7Q2MD"]
"""


def corpus_dict(**speaker) -> dict:
    spk = {
        "id": "v-k7q2md", "background": "native", "grew_up_hearing": "taiwan", "accent": "cmn-TW",
        "split": "gate", "sessions": ["K7Q2MD"],
    } | speaker
    return {
        "corpus": {"id": "volunteers-2026-10", "source": "volunteer-corpus", "kind": "recorded", "lect": "cmn"},
        "speaker": [spk],
    }


# ---- the data root ------------------------------------------------------------------------


def test_the_flag_beats_the_environment(tmp_path):
    assert data_root(tmp_path / "flag", environ={"TONEKIT_DATA": str(tmp_path / "env")}) == tmp_path / "flag"


def test_the_environment_beats_the_default(tmp_path):
    assert data_root(None, environ={"TONEKIT_DATA": str(tmp_path / "env")}) == tmp_path / "env"


def test_the_default_is_tonekit_data_in_the_home_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("TONEKIT_DATA", raising=False)
    assert data_root() == tmp_path / "tonekit-data"


@pytest.mark.parametrize("empty", ["", "   "])
def test_an_empty_environment_variable_is_unset(monkeypatch, tmp_path, empty):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert data_root(None, environ={"TONEKIT_DATA": empty}) == tmp_path / "tonekit-data"


def test_the_data_root_is_absolute_and_expands_the_home_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert data_root("~/vol") == tmp_path / "vol"
    assert data_root("rel/dir").is_absolute()


def test_the_layout_under_the_root():
    root = Path("/data")
    assert corpus_dir(root, "volunteers-2026-10") == root / "corpora" / "volunteers-2026-10"
    assert corpus_file_path(root, "c1") == root / "corpora" / "c1" / "corpus.toml"
    assert inbox_dir(root) == root / "inbox"
    assert purge_log_path(root) == root / "purge-log.jsonl"


# ---- corpus.toml --------------------------------------------------------------------------


def test_the_contracts_example_loads(tmp_path):
    path = tmp_path / "corpus.toml"
    path.write_text(EXAMPLE, encoding="utf-8")
    corpus = load_corpus_file(path)
    assert corpus.corpus.kind == "recorded" and corpus.corpus.manifest == "manifest.jsonl"
    [speaker] = corpus.speaker
    assert (speaker.id, speaker.accent, speaker.split, speaker.sessions) == ("v-k7q2md", "cmn-TW", "gate", ["K7Q2MD"])


def test_a_corpus_may_have_no_speakers_yet():
    data = corpus_dict()
    del data["speaker"]
    assert CorpusFile.model_validate(data).speaker == []


def test_the_manifest_defaults_to_manifest_jsonl():
    assert CorpusFile.model_validate(corpus_dict()).corpus.manifest == "manifest.jsonl"


def test_public_speakers_need_no_background_or_sessions():
    spk = Speaker.model_validate({"id": "SSB0005", "accent": "cmn-standard", "split": "calib"})
    assert (spk.background, spk.grew_up_hearing, spk.sessions) == (None, None, [])


@pytest.mark.parametrize("field,value", [
    ("split", "train"), ("background", "bilingual"), ("grew_up_hearing", "china"), ("accent", ""),
    ("id", "a b"), ("id", "../x"), ("id", ""), ("sessions", ["k7q2md"]), ("sessions", ["K7Q0MD"]),
])
def test_speaker_fields_are_checked(field, value):
    with pytest.raises(ValidationError) as e:
        Speaker.model_validate(corpus_dict(**{field: value})["speaker"][0])
    assert field in str(e.value)


@pytest.mark.parametrize("kind", ["recorded", "public", "synthetic"])
def test_every_kind_is_accepted(kind):
    data = corpus_dict()
    data["corpus"]["kind"] = kind
    assert CorpusFile.model_validate(data).corpus.kind == kind


@pytest.mark.parametrize("field,value", [
    ("kind", "live"), ("id", "Has Space"), ("id", ""), ("source", ""), ("lect", ""),
    ("manifest", "/abs/manifest.jsonl"), ("manifest", "../manifest.jsonl"), ("manifest", "a/../../m.jsonl"),
])
def test_corpus_fields_are_checked(field, value):
    data = corpus_dict()
    data["corpus"][field] = value
    with pytest.raises(ValidationError) as e:
        CorpusFile.model_validate(data)
    assert field in str(e.value)


def test_unknown_keys_are_errors():
    data = corpus_dict()
    data["corpus"]["name"] = "x"
    with pytest.raises(ValidationError, match="name"):
        CorpusFile.model_validate(data)
    with pytest.raises(ValidationError, match="email"):
        CorpusFile.model_validate(corpus_dict(email="x@y.z"))


def test_speaker_ids_are_unique_in_a_corpus():
    data = corpus_dict(id="dj", sessions=[])
    data["speaker"].append(dict(data["speaker"][0]))
    with pytest.raises(ValidationError, match="speaker 'dj' appears more than once"):
        CorpusFile.model_validate(data)


def test_a_session_belongs_to_one_speaker():
    data = corpus_dict()
    data["speaker"].append(dict(data["speaker"][0], id="dj"))
    with pytest.raises(ValidationError, match="session 'K7Q2MD' belongs to more than one speaker"):
        CorpusFile.model_validate(data)


def test_a_volunteer_speaker_id_names_its_session():
    with pytest.raises(ValidationError, match="speaker 'v-k7q2md': a volunteer id v-<code> needs sessions"):
        Speaker.model_validate(corpus_dict(sessions=["ABCDEF"])["speaker"][0])
    with pytest.raises(ValidationError, match="needs sessions"):
        Speaker.model_validate(corpus_dict(sessions=[])["speaker"][0])


def test_other_speaker_ids_may_have_any_sessions():
    assert Speaker.model_validate(corpus_dict(id="dj", sessions=[])["speaker"][0]).id == "dj"


def test_load_errors_name_the_file_and_the_speaker(tmp_path):
    path = tmp_path / "corpus.toml"
    path.write_text(EXAMPLE.replace('split = "gate"', 'split = "train"'), encoding="utf-8")
    with pytest.raises(RegistryError, match=r"corpus\.toml.*\n.*speaker 'v-k7q2md'\.split"):
        load_corpus_file(path)


def test_invalid_toml_names_the_file(tmp_path):
    path = tmp_path / "corpus.toml"
    path.write_text("[corpus\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="corpus.toml: invalid TOML"):
        load_corpus_file(path)


# ---- accents and splits -------------------------------------------------------------------


def test_taiwan_maps_to_cmn_tw_and_everything_else_to_standard():
    assert default_accent("taiwan") == "cmn-TW"
    for other in ("mainland", "singapore_malaysia", "hong_kong_macau", "other", "prefer_not"):
        assert default_accent(other) == "cmn-standard"


def test_an_unknown_lect_has_no_default_accent():
    with pytest.raises(LectError, match="'yue'"):
        default_accent("taiwan", lect="yue")


def test_volunteer_speaker_ids():
    assert volunteer_speaker_id("K7Q2MD") == "v-k7q2md"
    with pytest.raises(ValueError, match="'K7Q0MD'"):
        volunteer_speaker_id("K7Q0MD")


# Pinned (sha256 of the id, first 8 bytes big-endian, modulo 100: below 60 calib, below 80 dev, else
# heldout): these decide who is heldout, so a change would silently move speakers between splits.
GOLDEN_SPLITS = {
    "SSB0001": "calib", "SSB0002": "dev", "SSB0003": "dev", "SSB0004": "heldout", "SSB0005": "heldout",
    "SSB0010": "dev", "v-k7q2md": "calib", "dj": "heldout", "common-voice-zh-TW-0001": "calib",
}


def test_the_split_of_a_speaker_is_stable_forever():
    assert {k: hashed_split(k) for k in GOLDEN_SPLITS} == GOLDEN_SPLITS


def test_hashed_split_is_about_60_20_20():
    counts = {"calib": 0, "dev": 0, "heldout": 0}
    for i in range(5000):
        counts[hashed_split(f"speaker-{i}")] += 1
    assert 0.57 < counts["calib"] / 5000 < 0.63
    assert 0.17 < counts["dev"] / 5000 < 0.23
    assert 0.17 < counts["heldout"] / 5000 < 0.23


def test_hashed_split_never_assigns_gate():
    assert {hashed_split(f"s{i}") for i in range(300)} == {"calib", "dev", "heldout"}


def test_recorded_speakers_default_to_gate_and_the_rest_to_the_hash():
    assert default_split("recorded", "v-k7q2md") == "gate"
    assert default_split("recorded", "SSB0005") == "gate"
    assert default_split("public", "SSB0005") == hashed_split("SSB0005")
    assert default_split("synthetic", "SSB0005") == hashed_split("SSB0005")


# ---- the purge log ------------------------------------------------------------------------

RECORD = {"session": "K7Q2MD", "purged_at": "2026-10-05T09:00:00Z", "files_removed": 14, "corpora": ["volunteers-2026-10"]}


def test_a_purge_record_parses():
    r = PurgeRecord.model_validate(RECORD)
    assert (r.session, r.files_removed, r.corpora) == ("K7Q2MD", 14, ["volunteers-2026-10"])


@pytest.mark.parametrize("field,value", [
    ("session", "nope"), ("purged_at", "yesterday"), ("files_removed", -1), ("corpora", "c1"),
])
def test_purge_record_fields_are_checked(field, value):
    with pytest.raises(ValidationError) as e:
        PurgeRecord.model_validate(RECORD | {field: value})
    assert field in str(e.value)


def test_a_purge_record_has_no_extra_fields():
    with pytest.raises(ValidationError, match="note"):
        PurgeRecord.model_validate(RECORD | {"note": "x"})


def test_the_purge_log_loads_in_order_and_skips_blank_lines(tmp_path):
    path = tmp_path / "purge-log.jsonl"
    path.write_text(json.dumps(RECORD) + "\n\n" + json.dumps(RECORD | {"session": "ABCDEF"}) + "\n", encoding="utf-8")
    assert [r.session for r in load_purge_log(path)] == ["K7Q2MD", "ABCDEF"]


def test_no_purge_log_means_no_purges(tmp_path):
    assert load_purge_log(tmp_path / "purge-log.jsonl") == []


def test_a_bad_purge_log_line_is_named(tmp_path):
    path = tmp_path / "purge-log.jsonl"
    path.write_text(json.dumps(RECORD) + "\n{oops\n", encoding="utf-8")
    with pytest.raises(RegistryError, match=r"purge-log\.jsonl:2: invalid JSON"):
        load_purge_log(path)
    path.write_text(json.dumps(RECORD | {"session": "no"}) + "\n", encoding="utf-8")
    with pytest.raises(RegistryError, match=r"purge-log\.jsonl:1:.*session"):
        load_purge_log(path)
