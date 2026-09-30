"""Fixtures shared by the synthesis tests: the cmn pack and calibration, and two prepared sources on
the numpy harmonic test voice. They are session-scoped, since analysing a source is the slow part;
nothing in the harness mutates a `Source`."""

from __future__ import annotations

from pathlib import Path

import pytest
from synth_support import PACKS, quiet_clip

from tonekit_harness import source


@pytest.fixture(scope="session")
def pack_toml() -> str:
    return (PACKS / "cmn.toml").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def calib_json() -> str:
    return (PACKS / "cmn.calib.json").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("synth-sources")


@pytest.fixture(scope="session")
def src(root, pack_toml, calib_json) -> source.Source:
    """T4 T1 T3: syllable 1 is level, syllable 2 dips."""
    clip = quiet_clip(root, "src-413", ["4", "1", "3"])
    return source.prepare(clip, root=root, pack_toml=pack_toml, calib_json=calib_json)


@pytest.fixture(scope="session")
def src_neutral(root, pack_toml, calib_json) -> source.Source:
    """T1 T5 T2: syllable 1 is the neutral tone."""
    clip = quiet_clip(root, "src-152", ["1", "5", "2"])
    return source.prepare(clip, root=root, pack_toml=pack_toml, calib_json=calib_json)
