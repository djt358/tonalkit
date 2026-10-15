"""Silent clips. A take whose audio is all zeros, or whose peak is below -60 dBFS, is a microphone
that delivered nothing (a route change or an interruption on the phone). The kit refuses such takes
now; bundles from before that still carry them. Intake leaves them out: no row, no audio."""

from __future__ import annotations

import io
import wave

import numpy as np

from ..contracts.bundle import Bundle

SILENT_PEAK_DBFS = -60.0
_FULL_SCALE = 32768.0  # 16-bit PCM
_SILENT_PEAK = 10.0 ** (SILENT_PEAK_DBFS / 20.0)  # as a fraction of full scale


def is_silent(wav: bytes) -> bool:
    """Whether the (already header-checked, 16-bit mono) WAV peaks below SILENT_PEAK_DBFS;
    all zeros peaks at nothing at all."""
    with wave.open(io.BytesIO(wav), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return int(np.abs(pcm.astype(np.int32)).max(initial=0)) / _FULL_SCALE < _SILENT_PEAK


def silent_cards(bundle: Bundle) -> list[str]:
    """The cards of the bundle's clips that are silent, in the order session.json lists them."""
    return [c.card for c in bundle.session.clips if is_silent(bundle.clip_bytes(c.card))]
