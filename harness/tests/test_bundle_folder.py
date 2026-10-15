"""read_bundle on the folder a bundle zip unzips to: the same checks, Finder metadata left out."""

from __future__ import annotations

import json

import pytest
from bundle_support import make_bundle, session_dict, wav_bytes

from tonekit_harness.contracts.bundle import BundleError, read_bundle
from tonekit_harness.contracts.bundle_folder import is_os_metadata


def unzipped(tmp_path, session: dict | None = None, wavs: dict[str, bytes] | None = None):
    session = session or session_dict()
    wavs = {"clips/g01-c.wav": wav_bytes(), "clips/g01-e.wav": wav_bytes(800)} if wavs is None else wavs
    folder = tmp_path / "tonekit-s05-v1-K7Q2MD"
    (folder / "clips").mkdir(parents=True)
    (folder / "session.json").write_text(json.dumps(session), encoding="utf-8")
    for name, data in wavs.items():
        (folder / name).write_bytes(data)
    return folder


def test_a_folder_reads_like_its_zip(tmp_path):
    folder = unzipped(tmp_path)
    zipped = make_bundle(tmp_path / "b.zip", wavs={"clips/g01-c.wav": wav_bytes(), "clips/g01-e.wav": wav_bytes(800)})
    a, b = read_bundle(folder), read_bundle(zipped)
    assert a.path == folder
    assert (a.session, a.audio) == (b.session, b.audio)
    assert a.clip_bytes("g01-e") == wav_bytes(800)


def test_session_bytes_are_the_file_as_sent_from_a_folder_and_a_zip(tmp_path):
    folder = unzipped(tmp_path)
    assert read_bundle(folder).session_bytes() == (folder / "session.json").read_bytes()
    raw = json.dumps(session_dict(), indent=2).encode()
    assert read_bundle(make_bundle(tmp_path / "b.zip", raw)).session_bytes() == raw


def test_finder_metadata_is_left_out(tmp_path):
    folder = unzipped(tmp_path)
    (folder / ".DS_Store").write_bytes(b"\0finder")
    (folder / "clips" / "._g01-c.wav").write_bytes(b"appledouble")
    (folder / "__MACOSX").mkdir()
    (folder / "__MACOSX" / "session.json").write_bytes(b"x")
    assert set(read_bundle(folder).audio) == {"g01-c", "g01-e"}


def test_any_other_extra_file_is_refused_as_in_a_zip(tmp_path):
    folder = unzipped(tmp_path)
    (folder / "notes.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(BundleError, match="unexpected file 'notes.txt'"):
        read_bundle(folder)


def test_a_folder_missing_a_listed_clip_is_refused(tmp_path):
    folder = unzipped(tmp_path, wavs={"clips/g01-c.wav": wav_bytes()})
    with pytest.raises(BundleError, match="lists clips/g01-e.wav but the zip does not have it"):
        read_bundle(folder)


def test_a_folder_without_session_json_is_refused(tmp_path):
    (tmp_path / "empty").mkdir()
    with pytest.raises(BundleError, match="no session.json"):
        read_bundle(tmp_path / "empty")


@pytest.mark.parametrize(
    ("name", "metadata"),
    [(".DS_Store", True), ("clips/._a.wav", True), ("__MACOSX/x", True), ("clips/a.wav", False), ("session.json", False)],
)
def test_os_metadata_names(name, metadata):
    assert is_os_metadata(name) is metadata
