"""contracts.wav_check: the header check of a clip (16 kHz, mono, 16-bit PCM, all its audio) with a
message for each way a phone's file can be something else."""

import struct

import pytest
from bundle_support import make_bundle, wav_bytes

from tonekit_harness.contracts.bundle import BundleError, read_bundle
from tonekit_harness.contracts.wav_check import WavHeader, check_wav


def riff(chunks: bytes) -> bytes:
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def with_format_tag(tag: int, *, extensible: bool = False, frames: int = 1600) -> bytes:
    """A 16 kHz mono 16-bit WAV whose fmt chunk carries `tag` (an extensible one has the 40-byte fmt
    chunk with a PCM sub-format GUID)."""
    data = b"\x01\x00" * frames
    fmt = struct.pack("<HHIIHH", tag, 1, 16000, 32000, 2, 16)
    if extensible:
        guid = struct.pack("<H", 1) + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71"
        fmt += struct.pack("<HHI", 22, 16, 4) + guid
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data
    return riff(chunks)


def message(data: bytes) -> str:
    with pytest.raises(ValueError) as e:
        check_wav(data)
    return str(e.value)


def test_a_good_clip_gives_its_header():
    header = check_wav(wav_bytes(frames=1600))
    assert header == WavHeader(sample_rate=16000, channels=1, sample_width=2, frames=1600)
    assert header.duration_s == pytest.approx(0.1)


@pytest.mark.parametrize("data", [b"", b"RIFF", b"RI"])
def test_a_file_that_ends_too_soon_is_truncated(data):  # the wave module raises EOFError with no message
    assert message(data) == "not a PCM WAV (truncated)"


def test_no_cut_of_a_good_clip_escapes_as_another_exception():
    good = wav_bytes(frames=50)
    for n in range(len(good)):
        with pytest.raises(ValueError):
            check_wav(good[:n])


def test_text_is_not_a_wav():
    assert message(b"RIFFnope").startswith("not a PCM WAV (")
    assert message(b"hello, this is not audio at all").startswith("not a PCM WAV (")


def test_wave_format_extensible_is_named():  # what some recorders write for 16-bit mono
    out = message(with_format_tag(0xFFFE, extensible=True))
    assert "WAVE_FORMAT_EXTENSIBLE" in out and "plain" in out and "16-bit PCM" in out


@pytest.mark.parametrize("tag,name", [(3, "IEEE float"), (6, "A-law"), (7, "mu-law")])
def test_other_encodings_are_named(tag, name):
    out = message(with_format_tag(tag))
    assert name in out and "16-bit PCM" in out


def test_an_unlisted_encoding_gives_its_number():
    assert "format 85" in message(with_format_tag(85))


def test_wrong_rate_channels_and_width_are_listed_together():
    assert message(wav_bytes(rate=48000)) == "is 48000 Hz, 1 channel, 16-bit; need 16000 Hz, 1 channel, 16-bit"
    assert "2 channels" in message(wav_bytes(channels=2))
    assert "8-bit" in message(wav_bytes(width=1))


def test_no_audio_and_a_cut_file_are_different_problems():
    assert message(wav_bytes(frames=0)) == "has no audio"
    assert message(wav_bytes()[:-400]).startswith("truncated: the file ends before the audio")


def test_a_bundle_names_the_clip_and_the_reason(tmp_path):
    wavs = {"clips/g01-c.wav": b"", "clips/g01-e.wav": with_format_tag(0xFFFE, extensible=True)}
    with pytest.raises(BundleError) as e:
        read_bundle(make_bundle(tmp_path / "b.zip", wavs=wavs))
    out = str(e.value)
    assert "clips/g01-c.wav: not a PCM WAV (truncated)" in out
    assert "clips/g01-e.wav: is WAVE_FORMAT_EXTENSIBLE" in out
