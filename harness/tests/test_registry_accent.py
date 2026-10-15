"""The accent a speaker is graded against: their own, else the default for where they grew up
hearing Mandarin (R82, `contracts.registry.speaker_accent`); evaluate's --accent overrides. The
default is checked through corpus.toml as loaded, against the pack the corpora are graded with."""

from __future__ import annotations

import pytest
from registry_support import add_corpus, build_composed_root, speaker, speaker_clips, volunteer

from tonekit_harness.contracts.lects import LectError
from tonekit_harness.contracts.registry import RegistryError, Speaker
from tonekit_harness.registry import DataRoot, accent_for


def test_a_speakers_own_accent_wins_over_where_they_grew_up():
    spk = Speaker(id="s", split="calib", accent="cmn-standard", grew_up_hearing="taiwan")
    assert accent_for(spk) == "cmn-standard"


def test_the_override_beats_everything():
    spk = Speaker(id="s", split="calib", accent="cmn-TW", grew_up_hearing="taiwan")
    assert accent_for(spk, override="cmn-standard") == "cmn-standard"
    assert accent_for(spk, override="") == "cmn-TW"  # an empty --accent is no override


def test_without_an_accent_taiwan_is_cmn_tw():
    assert accent_for(Speaker(id="s", split="calib", grew_up_hearing="taiwan")) == "cmn-TW"


@pytest.mark.parametrize("hearing", ["mainland", "singapore_malaysia", "hong_kong_macau", "other", "prefer_not", None])
def test_without_an_accent_everyone_else_is_cmn_standard(hearing):
    assert accent_for(Speaker(id="s", split="calib", grew_up_hearing=hearing)) == "cmn-standard"


def test_a_lect_without_rules_has_no_default():
    with pytest.raises(LectError, match="'yue'"):
        accent_for(Speaker(id="s", split="calib", grew_up_hearing="taiwan"), lect="yue")
    assert accent_for(Speaker(id="s", split="calib", accent="yue-HK"), lect="yue") == "yue-HK"  # an explicit one needs none


# ---- through load -------------------------------------------------------------------------------


def test_a_selection_gives_each_speaker_their_accent_by_qualified_id(tmp_path):
    selection = DataRoot(build_composed_root(tmp_path)).select(kinds=["recorded"])
    assert selection.speakers["volunteers-2026-10/v-k7q2md"].accent is None  # as intake writes it
    assert selection.accents() == {
        "dj-2026-10/dj": "cmn-TW",  # stored in corpus.toml: wins although dj states no upbringing
        "volunteers-2026-10/v-k7q2md": "cmn-TW",  # grew up hearing taiwan, nothing stored
        "volunteers-2026-10/v-abcde2": "cmn-standard",  # mainland, nothing stored
    }
    assert set(selection.accents(override="cmn-standard").values()) == {"cmn-standard"}


def write_pack(path, *, lect: str = "cmn", accents: tuple[str, ...] = ("cmn-standard",)):
    """A pack TOML with what the registry reads of one: lect, tone ids, accent ids."""
    text = f'[pack]\nlect = "{lect}"\nbase_accent = "{accents[0]}"\n\n[[tone]]\nid = "1"\n'
    text += "".join(f'\n[[accent]]\nid = "{a}"\n' for a in accents)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_default_accent_the_pack_lacks_refuses_the_corpus_at_load(tmp_path):
    add_corpus(tmp_path / "data", "v", kind="recorded", source="volunteer-corpus",
               speakers=[volunteer("K7Q2MD", "taiwan")], clips=[])  # fmt: skip
    pack = write_pack(tmp_path / "standard-only.toml")
    with pytest.raises(RegistryError, match=r"speaker 'v-k7q2md': default accent 'cmn-TW' is not an accent of the pack"):
        DataRoot(tmp_path / "data", pack=pack).corpus("v")
    assert DataRoot(tmp_path / "data").corpus("v").speakers["v-k7q2md"].accent is None  # packs/cmn has cmn-TW


def test_the_corpora_are_checked_against_the_pack_they_are_graded_with(tmp_path):
    add_corpus(tmp_path / "data", "d", kind="recorded", source="dj-corpus",
               speakers=[speaker("dj")], clips=speaker_clips("dj", "dj-corpus"))  # fmt: skip
    pack = write_pack(tmp_path / "yue.toml", lect="yue", accents=("yue-HK",))
    with pytest.raises(RegistryError, match=r"corpus lect 'cmn' but the pack is for 'yue'"):
        DataRoot(tmp_path / "data", pack=pack).select()
