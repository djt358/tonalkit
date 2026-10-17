"""A public corpus's audio as the corpus keeps it: 16 kHz mono PCM16 WAV (docs/s05/contracts.md
section 3), resampled from whatever rate and channels the download has (`ingest`)."""

from __future__ import annotations

import struct
from pathlib import Path

from scipy.io import wavfile

from ..ingest import pcm16_wav, read_16k_mono, strict_wav_warnings


def converted(path: Path) -> bytes | None:
    """The WAV file at `path` as 16 kHz mono PCM16 WAV bytes; None if it cannot be read or holds
    no samples (the utterance is then dropped, and counted)."""
    try:
        with strict_wav_warnings():
            samples = read_16k_mono(path)
    except (OSError, ValueError, struct.error, wavfile.WavFileWarning):
        return None
    return pcm16_wav(samples) if samples.size else None
