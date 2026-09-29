"""Shared inputs for the tonekit_py tests: the cmn pack and the checked-in 4-1-3 recording."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from support import RATE

REPO = Path(__file__).resolve().parents[3]
PACKS = REPO / "packs" / "cmn"
FIXTURES = REPO / "fixtures"


@pytest.fixture(scope="session")
def pack_toml() -> str:
    return (PACKS / "cmn.toml").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def calib_json() -> str:
    return (PACKS / "cmn.calib.json").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def pcm() -> np.ndarray:
    """`fixtures/spoken-413.wav` as float32 in -1..1 (WAVE_FORMAT_EXTENSIBLE, 16 kHz mono)."""
    rate, samples = wavfile.read(FIXTURES / "spoken-413.wav")
    assert rate == RATE
    assert samples.dtype == np.float32 and samples.ndim == 1
    return samples


@pytest.fixture(scope="session")
def expected_assessment() -> dict:
    return json.loads((FIXTURES / "spoken-413.assessment.json").read_text(encoding="utf-8"))
