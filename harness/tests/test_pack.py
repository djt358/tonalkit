"""contracts.pack: the tone inventory of a language pack, read from its TOML."""

import pytest

from tonekit_harness.contracts.pack import PackError, default_pack_path, load_pack_info


def test_the_default_pack_is_the_cmn_pack():
    info = load_pack_info(None)
    assert default_pack_path().name == "cmn.toml"
    assert info.lect == "cmn"
    assert info.tone_ids == frozenset({"1", "2", "3", "4", "5"})
    assert info.accent_ids == frozenset({"cmn-standard", "cmn-TW"})


def test_a_pack_path_is_read(tmp_path):
    p = tmp_path / "x.toml"
    p.write_text('[pack]\nlect = "xx"\n[[tone]]\nid = "H"\n[[tone]]\nid = "L"\n[[accent]]\nid = "xx-a"\n', encoding="utf-8")
    info = load_pack_info(p)
    assert (info.lect, info.tone_ids, info.accent_ids) == ("xx", frozenset({"H", "L"}), frozenset({"xx-a"}))


def test_a_pack_may_have_no_accents(tmp_path):
    p = tmp_path / "x.toml"
    p.write_text('[pack]\nlect = "xx"\n[[tone]]\nid = "H"\n', encoding="utf-8")
    assert load_pack_info(p).accent_ids == frozenset()


@pytest.mark.parametrize("toml,message", [
    ("[pack\n", "invalid TOML"),
    ('[[tone]]\nid = "1"\n', r"no \[pack\] lect"),
    ('[pack]\nlect = "xx"\n', r"no \[\[tone\]\]"),
    ('[pack]\nlect = "xx"\n[[tone]]\nname = "x"\n', "without an id"),
    ('[pack]\nlect = "xx"\n[[tone]]\nid = "1"\n[[tone]]\nid = "1"\n', "duplicate tone id '1'"),
    ('[pack]\nlect = "xx"\n[[tone]]\nid = "1"\n[[accent]]\nname = "x"\n', "a \\[\\[accent\\]\\] without an id"),
    ('[pack]\nlect = "xx"\n[[tone]]\nid = "1"\n[[accent]]\nid = "a"\n[[accent]]\nid = "a"\n', "duplicate accent id 'a'"),
])
def test_a_bad_pack_says_what_is_wrong(tmp_path, toml, message):
    p = tmp_path / "bad.toml"
    p.write_text(toml, encoding="utf-8")
    with pytest.raises(PackError, match=message) as e:
        load_pack_info(p)
    assert str(p) in str(e.value)
