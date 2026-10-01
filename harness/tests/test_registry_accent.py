"""The accent a speaker is graded against: their own, else the default for where they grew up
hearing Mandarin; evaluate's --accent overrides."""

from __future__ import annotations

import pytest
from registry_support import build_composed_root

from tonekit_harness.contracts.lects import LectError
from tonekit_harness.contracts.registry import Speaker
from tonekit_harness.registry import DataRoot, accent_for


def without_accent(hearing: str | None) -> Speaker:
    """A speaker as intake might build one before its accent is chosen. The model requires an
    accent today, so this is `model_construct` (no validation)."""
    return Speaker.model_construct(id="s", split="calib", accent="", grew_up_hearing=hearing, sessions=[])


def test_a_speakers_own_accent_wins_over_where_they_grew_up():
    spk = Speaker(id="s", split="calib", accent="cmn-standard", grew_up_hearing="taiwan")
    assert accent_for(spk) == "cmn-standard"


def test_the_override_beats_everything():
    spk = Speaker(id="s", split="calib", accent="cmn-TW", grew_up_hearing="taiwan")
    assert accent_for(spk, override="cmn-standard") == "cmn-standard"
    assert accent_for(spk, override="") == "cmn-TW"  # an empty --accent is no override


def test_without_an_accent_taiwan_is_cmn_tw():
    assert accent_for(without_accent("taiwan")) == "cmn-TW"


@pytest.mark.parametrize("hearing", ["mainland", "singapore_malaysia", "hong_kong_macau", "other", "prefer_not", None])
def test_without_an_accent_everyone_else_is_cmn_standard(hearing):
    assert accent_for(without_accent(hearing)) == "cmn-standard"


def test_a_lect_without_rules_has_no_default():
    with pytest.raises(LectError, match="'yue'"):
        accent_for(without_accent("taiwan"), lect="yue")
    assert accent_for(Speaker(id="s", split="calib", accent="yue-HK"), lect="yue") == "yue-HK"  # an explicit one needs none


def test_a_selection_gives_each_speaker_their_accent_by_qualified_id(tmp_path):
    selection = DataRoot(build_composed_root(tmp_path)).select(kinds=["recorded"])
    assert selection.accents() == {
        "dj-2026-10/dj": "cmn-standard",
        "volunteers-2026-10/v-k7q2md": "cmn-TW",
        "volunteers-2026-10/v-abcde2": "cmn-standard",
    }
    assert set(selection.accents(override="cmn-TW").values()) == {"cmn-TW"}
