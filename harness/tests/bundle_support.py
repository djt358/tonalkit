"""Session bundles for tests: a valid session.json, tiny generated WAVs (stdlib `wave`) and zips of
them. Synthetic only: no recordings of people ever enter the repository."""

from __future__ import annotations

import copy
import io
import json
import struct
import wave
import zipfile
from pathlib import Path


def session_dict(**overrides) -> dict:
    base = {
        "schema": "tonekit.session.v1",
        "deck": {"id": "s05-v1", "sha256": "ab" * 32},
        "session": "K7Q2MD",
        "started_at": "2026-10-03T18:02:11Z",
        "finished_at": "2026-10-03T18:24:40Z",
        "consent": {"version": "v1", "agreed_at": "2026-10-03T18:02:30Z"},
        "speaker": {
            "background": "native",
            "grew_up_hearing": "taiwan",
            "reading": "hanzi+pinyin",
            "script": "traditional",
        },
        "device": {
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
            "input_sample_rate": 48000,
            "constraints": {"echoCancellation": False, "noiseSuppression": False, "autoGainControl": False},
        },
        "clips": [
            {"card": "g01-c", "file": "clips/g01-c.wav", "takes": 2, "duration_s": 0.1, "peak": 0.51},
            {"card": "g01-e", "file": "clips/g01-e.wav", "takes": 1, "duration_s": 0.1, "peak": 0.4},
        ],
        "skipped": ["d05-a"],
    }
    base.update(copy.deepcopy(overrides))
    return base


def wav_bytes(frames: int = 1600, rate: int = 16000, channels: int = 1, width: int = 2, level: int = 1) -> bytes:
    """A WAV of `frames` frames of a constant level (not a recording of anything): `level` is the
    16-bit sample value, 1 by default (-90 dBFS); other widths are a fixed byte."""
    sample = struct.pack("<h", level) if width == 2 else b"\x80" * width
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(sample * channels * frames)
    return buf.getvalue()


def make_bundle(
    path: Path,
    session: dict | str | bytes | None = None,
    wavs: dict[str, bytes] | None = None,
    extra: dict[str, bytes] | None = None,
) -> Path:
    """A bundle zip at `path`: session.json, the clips (member name -> bytes; default: both listed
    clips) and any `extra` members. `session` may be raw text or bytes to test broken JSON."""
    if session is None:
        session = session_dict()
    if wavs is None:
        wavs = {"clips/g01-c.wav": wav_bytes(), "clips/g01-e.wav": wav_bytes()}
    if isinstance(session, dict):
        session = json.dumps(session)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("session.json", session)
        for name, data in {**wavs, **(extra or {})}.items():
            z.writestr(name, data)
    return path
