"""R80: the consent says "never clone or imitate your voice", and WORLD resynthesis would. So the one
door every perturbation comes through (`source.prepare`, and `load_sources` in front of it) refuses
clips whose source is the volunteer corpus, and `tkh synth` and `tkh adversary` fail with the reason."""

import pytest
from support import write_manifest
from synth_support import PACKS, quiet_clip

from tonekit_harness import cli, source
from tonekit_harness.family import SynthError

VOLUNTEERS = "volunteer-corpus"
WHY = "volunteers' recordings are never resynthesised"


def test_the_refused_source_is_the_register_row_for_volunteers():
    assert source.NEVER_RESYNTHESISED == VOLUNTEERS


def test_prepare_refuses_a_volunteer_clip_naming_it(root, pack_toml):
    clip = quiet_clip(root, "vol-1", ["4", "1", "3"], source=VOLUNTEERS)
    with pytest.raises(SynthError, match=f"vol-1: {WHY}"):
        source.prepare(clip, root=root, pack_toml=pack_toml)


def test_a_clip_from_any_other_source_is_still_prepared(root, pack_toml):
    clip = quiet_clip(root, "dj-1", ["4", "1", "3"], source="dj-corpus")
    assert source.prepare(clip, root=root, pack_toml=pack_toml).clip.id == "dj-1"


def test_load_sources_refuses_a_mixed_manifest_before_analysing_anything(tmp_path, monkeypatch):
    clips = [
        quiet_clip(tmp_path, "dj-1", ["4", "1", "3"], source="dj-corpus"),
        quiet_clip(tmp_path, "vol-1", ["4", "1", "3"], source=VOLUNTEERS),
    ]
    manifest_path = write_manifest(tmp_path / "manifest.jsonl", clips)

    def analysed(*args, **kwargs):
        raise AssertionError("nothing may be analysed from a manifest that holds volunteer audio")

    monkeypatch.setattr(source, "prepare", analysed)
    with pytest.raises(SynthError, match=f"vol-1: {WHY}"):
        list(source.load_sources(manifest_path, PACKS / "cmn.toml", None, None))


@pytest.mark.parametrize("command", ["synth", "adversary"])
def test_the_commands_stop_with_the_reason_and_write_nothing(command, tmp_path, capsys):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    clip = quiet_clip(corpus, "vol-1", ["4", "1", "3"], source=VOLUNTEERS)
    manifest_path = write_manifest(corpus / "manifest.jsonl", [clip])
    out = tmp_path / "out"
    specific = ["--per-clip", "1"] if command == "synth" else ["--trials", "1", "--theta", "0.5"]

    code = cli.main(
        [command, "--manifest", str(manifest_path), "--pack", str(PACKS / "cmn.toml"),
         "--out", str(out), *specific]
    )  # fmt: skip

    assert code == 1
    assert WHY in capsys.readouterr().err
    assert not out.exists()
