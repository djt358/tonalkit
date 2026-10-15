"""The header check of a clip in a session bundle: a 16 kHz mono 16-bit PCM WAV with all the audio
its header promises. It says why a phone's file is something else; decoding and quality control of
the audio are intake's job."""

from __future__ import annotations

import io
import re
import struct
import wave
from dataclasses import dataclass

CLIP_RATE, CLIP_CHANNELS, CLIP_SAMPLE_WIDTH = 16_000, 1, 2  # Hz, mono, 16-bit bytes

# fmt chunk format tags a recorder may write instead of plain PCM
_PCM = 1
_FORMAT_NAMES = {3: "IEEE float", 6: "A-law", 7: "mu-law", 0xFFFE: "WAVE_FORMAT_EXTENSIBLE"}
_UNKNOWN_FORMAT = re.compile(r"unknown format: (\d+)")


@dataclass(frozen=True)
class WavHeader:
    sample_rate: int
    channels: int
    sample_width: int  # bytes per sample
    frames: int

    @property
    def duration_s(self) -> float:
        return self.frames / self.sample_rate


def check_wav(data: bytes) -> WavHeader:
    """The header of a 16 kHz mono 16-bit PCM WAV with all its audio, else a ValueError saying what
    is wrong (the clip's name is the caller's to add)."""
    tag = _format_tag(data)
    if tag is not None and tag != _PCM:
        raise ValueError(_format_problem(tag))
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            header = WavHeader(w.getframerate(), w.getnchannels(), w.getsampwidth(), w.getnframes())
            whole = len(w.readframes(header.frames)) == header.frames * header.channels * header.sample_width
    except (EOFError, struct.error):  # the file ends inside the RIFF or fmt header
        raise ValueError("not a PCM WAV (truncated)") from None
    except wave.Error as e:
        raise ValueError(_wave_error(e)) from None
    if (header.sample_rate, header.channels, header.sample_width) != (CLIP_RATE, CLIP_CHANNELS, CLIP_SAMPLE_WIDTH):
        s = "s" if header.channels != 1 else ""
        raise ValueError(
            f"is {header.sample_rate} Hz, {header.channels} channel{s}, {8 * header.sample_width}-bit; "
            "need 16000 Hz, 1 channel, 16-bit"
        )
    if header.frames == 0:
        raise ValueError("has no audio")
    if not whole:
        raise ValueError("truncated: the file ends before the audio the header promises")
    return header


def _format_tag(data: bytes) -> int | None:
    """The fmt chunk's format tag, read here so the answer doesn't depend on the Python version
    (`wave` reads WAVE_FORMAT_EXTENSIBLE from 3.12 on); None when the file has no readable fmt chunk
    (`wave` then says what is wrong)."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    at = 12
    while at + 8 <= len(data):
        chunk, size = data[at : at + 4], struct.unpack_from("<I", data, at + 4)[0]
        if chunk == b"fmt ":
            return struct.unpack_from("<H", data, at + 8)[0] if at + 10 <= len(data) else None
        at += 8 + size + (size & 1)
    return None


def _format_problem(tag: int) -> str:
    name = _FORMAT_NAMES.get(tag, f"format {tag}")
    return f"is {name}, not plain PCM; need 16-bit PCM at 16000 Hz, 1 channel"


def _wave_error(e: wave.Error) -> str:
    """The module only reads plain PCM: a file in another encoding is `unknown format: <tag>`."""
    m = _UNKNOWN_FORMAT.fullmatch(str(e))
    if m is None:
        return f"not a PCM WAV ({e})"
    return _format_problem(int(m.group(1)))
