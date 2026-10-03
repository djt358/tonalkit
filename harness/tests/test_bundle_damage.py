"""contracts.bundle: a damaged zip (a phone share that was cut, a flipped byte) is a BundleError that
lists every damaged member, never a raw zipfile or zlib exception."""

import lzma
import zipfile
import zlib
from pathlib import Path

import pytest
from bundle_support import make_bundle, wav_bytes

from tonekit_harness.contracts.bundle import BundleError, read_bundle

# distinct lengths so each clip's bytes can be found in the (stored, uncompressed) zip
CLIP_C, CLIP_E = wav_bytes(frames=1600), wav_bytes(frames=1700)


def stored_bundle(tmp_path: Path) -> Path:
    return make_bundle(tmp_path / "b.zip", wavs={"clips/g01-c.wav": CLIP_C, "clips/g01-e.wav": CLIP_E})


def flip_last_byte_of(path: Path, member_bytes: bytes) -> None:
    """Flip one bit in the last byte of a stored member: the WAV header stays valid, so only the
    zip's CRC can tell."""
    raw = bytearray(path.read_bytes())
    at = raw.index(member_bytes) + len(member_bytes) - 1
    raw[at] ^= 0x01
    path.write_bytes(bytes(raw))


def bundle_error(path: Path) -> str:
    with pytest.raises(BundleError) as e:
        read_bundle(path)
    return str(e.value)


def test_an_undamaged_stored_bundle_reads(tmp_path):
    assert set(read_bundle(stored_bundle(tmp_path)).audio) == {"g01-c", "g01-e"}


def test_a_flipped_byte_in_a_clip_is_a_damaged_member(tmp_path):
    path = stored_bundle(tmp_path)
    flip_last_byte_of(path, CLIP_E)
    out = bundle_error(path)
    assert "clips/g01-e.wav: damaged (" in out and "CRC" in out
    assert "clips/g01-c.wav" not in out


def test_a_flipped_byte_in_session_json_is_a_damaged_member(tmp_path):
    path = stored_bundle(tmp_path)
    text = zipfile.ZipFile(path).read("session.json")
    flip_last_byte_of(path, text)
    out = bundle_error(path)
    assert "session.json: damaged (" in out and "CRC" in out


def test_every_damaged_member_is_listed(tmp_path):
    path = stored_bundle(tmp_path)
    flip_last_byte_of(path, CLIP_C)
    flip_last_byte_of(path, CLIP_E)
    out = bundle_error(path)
    assert "clips/g01-c.wav: damaged" in out and "clips/g01-e.wav: damaged" in out


def test_damaged_clips_are_listed_even_when_session_json_is_damaged(tmp_path):
    path = stored_bundle(tmp_path)
    flip_last_byte_of(path, zipfile.ZipFile(path).read("session.json"))
    flip_last_byte_of(path, CLIP_E)
    out = bundle_error(path)
    assert "session.json: damaged" in out and "clips/g01-e.wav: damaged" in out


def test_other_problems_are_listed_with_the_damage(tmp_path):
    path = make_bundle(
        tmp_path / "b.zip",
        wavs={"clips/g01-c.wav": wav_bytes(rate=44100), "clips/g01-e.wav": CLIP_E},
    )
    flip_last_byte_of(path, CLIP_E)
    out = bundle_error(path)
    assert "clips/g01-c.wav" in out and "44100 Hz" in out and "clips/g01-e.wav: damaged" in out


@pytest.mark.parametrize(
    "raised",
    [
        zipfile.BadZipFile("Bad CRC-32 for file"),
        zlib.error("Error -3 while decompressing data: invalid stored block lengths"),
        NotImplementedError("That compression method is not supported"),
        RuntimeError("File 'x' is encrypted, password required for extraction"),
        EOFError("Compressed file ended before the end-of-stream marker was reached"),
    ],
    ids=lambda e: type(e).__name__,
)
@pytest.mark.parametrize("member", ["session.json", "clips/g01-c.wav"])
def test_every_way_a_member_read_can_fail_is_a_damaged_member(tmp_path, monkeypatch, raised, member):
    path = stored_bundle(tmp_path)
    real_read = zipfile.ZipFile.read

    def read(self, name, pwd=None):
        if name == member:
            raise raised
        return real_read(self, name, pwd)

    monkeypatch.setattr(zipfile.ZipFile, "read", read)
    out = bundle_error(path)
    assert f"{member}: damaged ({raised})" in out


def compressed_bundle(path: Path, compression: int) -> Path:
    """The bundle's members written with `compression` (bz2 or lzma), which stored_bundle is not."""
    members = {
        "session.json": zipfile.ZipFile(stored_bundle(path.parent)).read("session.json"),
        "clips/g01-c.wav": CLIP_C,
        "clips/g01-e.wav": CLIP_E,
    }
    with zipfile.ZipFile(path, "w", compression=compression) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def break_stream(path: Path, member: str, at: int, value: int) -> None:
    """Set one byte of a compressed member's data (`at` bytes in) so its stream cannot be decoded."""
    info = zipfile.ZipFile(path).getinfo(member)
    raw = bytearray(path.read_bytes())
    start = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
    raw[start + at] = value
    path.write_bytes(bytes(raw))


@pytest.mark.parametrize("compression,at,value,error", [
    (zipfile.ZIP_BZIP2, 0, 0x00, OSError),  # the BZh magic
    (zipfile.ZIP_LZMA, 4, 0xFF, lzma.LZMAError),  # the LZMA properties byte
], ids=["bz2", "lzma"])
def test_a_broken_bz2_or_lzma_member_is_a_damaged_member(tmp_path, compression, at, value, error):
    path = compressed_bundle(tmp_path / "c.zip", compression)
    assert set(read_bundle(path).audio) == {"g01-c", "g01-e"}
    break_stream(path, "clips/g01-e.wav", at, value)
    with pytest.raises(error):  # what zipfile raises: the reason _DAMAGE must name it
        zipfile.ZipFile(path).read("clips/g01-e.wav")
    out = bundle_error(path)
    assert "clips/g01-e.wav: damaged (" in out
    assert "clips/g01-c.wav" not in out


def test_a_truncated_zip_is_not_a_zip(tmp_path):
    path = stored_bundle(tmp_path)
    path.write_bytes(path.read_bytes()[:-30])
    assert f"{path}: not a zip file" in bundle_error(path)
