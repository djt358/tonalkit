"""contracts.bundle: session.json (contracts.md section 2) and the zip layout the kit exports."""

import json
import zipfile

import pytest
from bundle_support import make_bundle, session_dict, wav_bytes
from pydantic import ValidationError

from tonekit_harness.contracts.bundle import (
    SESSION_ALPHABET,
    BundleError,
    Session,
    read_bundle,
)

# ---- session.json -------------------------------------------------------------------------


def invalid(**overrides) -> str:
    with pytest.raises(ValidationError) as e:
        Session.model_validate(session_dict(**overrides))
    return str(e.value)


def test_the_contracts_example_is_valid():
    s = Session.model_validate(session_dict())
    assert s.session == "K7Q2MD" and s.speaker.grew_up_hearing == "taiwan"
    assert s.deck.id == "s05-v1" and [c.card for c in s.clips] == ["g01-c", "g01-e"]
    assert s.skipped == ["d05-a"]


def test_the_alphabet_has_no_ambiguous_characters():
    assert len(SESSION_ALPHABET) == 32 and len(set(SESSION_ALPHABET)) == 32
    assert not set("01OI") & set(SESSION_ALPHABET)


def test_every_alphabet_character_is_accepted_in_a_code():
    for start in range(0, 32, 6):
        code = (SESSION_ALPHABET * 2)[start : start + 6]
        assert Session.model_validate(session_dict(session=code)).session == code


@pytest.mark.parametrize("code", ["K7Q2M", "K7Q2MDX", "k7q2md", "K7Q0MD", "K7QOMD", "K7Q1MD", "K7QIMD", "K7Q2M!", ""])
def test_bad_session_codes(code):
    assert "session" in invalid(session=code)


def test_the_schema_tag_is_checked():
    assert "schema" in invalid(schema="tonekit.session.v2")


@pytest.mark.parametrize(
    "path,value",
    [
        (("speaker", "background"), "bilingual"),
        (("speaker", "grew_up_hearing"), "china"),
        (("speaker", "reading"), "pinyin"),
    ],
)
def test_speaker_fields_are_enums(path, value):
    speaker = dict(session_dict()["speaker"], **{path[1]: value})
    assert path[1] in invalid(speaker=speaker)


@pytest.mark.parametrize(
    "background", ["native", "heritage", "learner", "prefer_not"]
)
def test_every_background_is_accepted(background):
    speaker = dict(session_dict()["speaker"], background=background)
    assert Session.model_validate(session_dict(speaker=speaker)).speaker.background == background


@pytest.mark.parametrize("where", ["top", "speaker", "device", "consent"])
def test_no_names_or_contact_details_anywhere(where):
    data = session_dict()
    (data if where == "top" else data[where])["email"] = "someone@example.com"
    with pytest.raises(ValidationError, match="email"):
        Session.model_validate(data)


def test_a_session_may_not_finish_before_it_starts():
    assert "finished_at" in invalid(finished_at="2026-10-03T18:00:00Z")


def test_timestamps_carry_a_time_zone():
    assert "started_at" in invalid(started_at="2026-10-03T18:02:11")


def test_the_deck_hash_is_64_hex_digits():
    assert "sha256" in invalid(deck={"id": "s05-v1", "sha256": "xyz"})
    assert "sha256" in invalid(deck={"id": "s05-v1", "sha256": "AB" * 32})


@pytest.mark.parametrize(
    "field,value",
    [("input_sample_rate", 0), ("user_agent", "")],
)
def test_device_fields(field, value):
    device = dict(session_dict()["device"], **{field: value})
    assert field in invalid(device=device)


def test_device_constraints_record_all_three_settings():
    device = session_dict()["device"]
    device["constraints"] = {"echoCancellation": False, "noiseSuppression": False}
    assert "autoGainControl" in invalid(device=device)


def test_a_constraint_the_browser_did_not_report_may_be_null():
    device = session_dict()["device"]
    device["constraints"]["autoGainControl"] = None
    assert Session.model_validate(session_dict(device=device)).device.constraints.autoGainControl is None


@pytest.mark.parametrize(
    "change",
    [{"takes": 0}, {"duration_s": 0}, {"peak": 1.5}, {"peak": -0.1}, {"card": "G01"}, {"file": "clips/other.wav"},
     {"file": "g01-c.wav"}],
)
def test_clip_entries(change):
    clips = session_dict()["clips"]
    clips[0] = dict(clips[0], **change)
    assert "clips.0" in invalid(clips=clips)


def test_a_card_is_listed_once():
    clips = session_dict()["clips"]
    out = invalid(clips=[clips[0], clips[0]])
    assert "g01-c" in out and "more than once" in out


def test_a_skipped_card_has_no_clip():
    out = invalid(skipped=["g01-c"])
    assert "g01-c" in out and "both skipped and recorded" in out


def test_skipped_entries_are_card_ids():
    assert "skipped" in invalid(skipped=["D05_A"])


def test_a_card_is_skipped_once():
    assert "more than once" in invalid(skipped=["d05-a", "d05-a"])


# ---- the zip ------------------------------------------------------------------------------


def bundle_error(path) -> str:
    with pytest.raises(BundleError) as e:
        read_bundle(path)
    return str(e.value)


def test_a_valid_bundle_reads(tmp_path):
    path = make_bundle(tmp_path / "tonekit-s05-v1-K7Q2MD.zip")
    bundle = read_bundle(path)
    assert bundle.path == path and bundle.session.session == "K7Q2MD"
    assert set(bundle.audio) == {"g01-c", "g01-e"}
    header = bundle.audio["g01-c"]
    assert (header.sample_rate, header.channels, header.sample_width, header.frames) == (16000, 1, 2, 1600)
    assert header.duration_s == pytest.approx(0.1)


def test_clip_bytes_are_the_wav_in_the_zip(tmp_path):
    bundle = read_bundle(make_bundle(tmp_path / "b.zip"))
    assert bundle.clip_bytes("g01-e") == wav_bytes()
    with pytest.raises(KeyError, match="nope"):
        bundle.clip_bytes("nope")


def test_a_bundle_with_no_clips_is_valid(tmp_path):
    data = session_dict(clips=[], skipped=["g01-c", "g01-e"])
    assert read_bundle(make_bundle(tmp_path / "b.zip", data, wavs={})).audio == {}


def test_not_a_zip(tmp_path):
    path = tmp_path / "b.zip"
    path.write_text("hello")
    assert f"{path}: not a zip file" in bundle_error(path)


def test_a_missing_file(tmp_path):
    assert "does not exist" in bundle_error(tmp_path / "nope.zip")


def test_no_session_json(tmp_path):
    path = tmp_path / "b.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("clips/g01-c.wav", wav_bytes())
    assert f"{path}: no session.json" in bundle_error(path)


def test_session_json_must_be_json(tmp_path):
    assert "session.json: invalid JSON" in bundle_error(make_bundle(tmp_path / "b.zip", "{oops"))


def test_session_json_must_be_an_object(tmp_path):
    assert "session.json: expected a JSON object" in bundle_error(make_bundle(tmp_path / "b.zip", "[]"))


def test_session_json_must_be_utf8(tmp_path):
    assert "session.json" in bundle_error(make_bundle(tmp_path / "b.zip", b"\xff\xfe"))


def test_session_json_problems_name_the_field(tmp_path):
    out = bundle_error(make_bundle(tmp_path / "b.zip", session_dict(session="nope")))
    assert "session.json" in out and "session" in out


def test_a_listed_clip_must_be_in_the_zip(tmp_path):
    path = make_bundle(tmp_path / "b.zip", wavs={"clips/g01-c.wav": wav_bytes()})
    assert "session.json lists clips/g01-e.wav but the zip does not have it" in bundle_error(path)


def test_a_clip_in_the_zip_must_be_listed(tmp_path):
    path = make_bundle(tmp_path / "b.zip", extra={"clips/z99.wav": wav_bytes()})
    assert "clips/z99.wav is in the zip but not listed in session.json" in bundle_error(path)


@pytest.mark.parametrize("name", ["notes.txt", "__MACOSX/._session.json", "clips/sub/g01-c.wav", "clips/G01.wav",
                                  "../clips/g01-c.wav", "/clips/g01-c.wav", "clips/g01-c.mp3", "clips\\g01-c.wav"])
def test_nothing_else_belongs_in_the_zip(tmp_path, name):
    path = make_bundle(tmp_path / "b.zip", extra={name: b"x"})
    assert f"unexpected file {name!r}" in bundle_error(path)


def test_a_member_name_may_not_repeat(tmp_path):
    path = make_bundle(tmp_path / "b.zip")
    with pytest.warns(UserWarning, match="Duplicate name"), zipfile.ZipFile(path, "a") as z:
        z.writestr("clips/g01-c.wav", wav_bytes())
    assert "clips/g01-c.wav appears twice" in bundle_error(path)


@pytest.mark.parametrize(
    "wav,problem",
    [
        (wav_bytes(rate=48000), "48000 Hz"),
        (wav_bytes(channels=2), "2 channels"),
        (wav_bytes(width=1), "8-bit"),
        (wav_bytes(frames=0), "no audio"),
    ],
)
def test_the_wav_must_be_16k_mono_16_bit(tmp_path, wav, problem):
    path = make_bundle(tmp_path / "b.zip", wavs={"clips/g01-c.wav": wav, "clips/g01-e.wav": wav_bytes()})
    out = bundle_error(path)
    assert "clips/g01-c.wav" in out and problem in out
    assert "clips/g01-e.wav" not in out


def test_a_truncated_wav_is_refused(tmp_path):
    cut = wav_bytes()[:-400]
    path = make_bundle(tmp_path / "b.zip", wavs={"clips/g01-c.wav": cut, "clips/g01-e.wav": wav_bytes()})
    assert "clips/g01-c.wav: truncated" in bundle_error(path)


def test_not_a_wav(tmp_path):
    path = make_bundle(tmp_path / "b.zip", wavs={"clips/g01-c.wav": b"RIFFnope", "clips/g01-e.wav": wav_bytes()})
    assert "clips/g01-c.wav: not a PCM WAV" in bundle_error(path)


def test_every_problem_is_listed(tmp_path):
    path = make_bundle(
        tmp_path / "b.zip",
        wavs={"clips/g01-c.wav": wav_bytes(rate=44100), "clips/g01-e.wav": wav_bytes(channels=2)},
    )
    out = bundle_error(path)
    assert "clips/g01-c.wav" in out and "clips/g01-e.wav" in out


def test_the_session_json_text_is_what_is_parsed(tmp_path):
    path = make_bundle(tmp_path / "b.zip", json.dumps(session_dict(), indent=2, ensure_ascii=False))
    assert read_bundle(path).session.consent.version == "v1"
