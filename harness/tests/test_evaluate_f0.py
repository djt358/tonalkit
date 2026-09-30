"""`evaluate.run(..., f0=...)`: grading with an f0 provider other than tonekit's own pYIN. The
default (`f0=None`) must stay exactly what it was: the same results and the same cache keys."""

from __future__ import annotations

import hashlib
import json

import pytest
from support import gate_corpus, make_clip

from tonekit_harness import evaluate, pitch_tracks
from tonekit_harness.evaluate import EvalError


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    root = tmp_path_factory.mktemp("f0-corpus")
    return root, gate_corpus(root)


def old_cache_key(wav: bytes, register_json: str | None) -> str:
    """The analysis cache key as it was before f0 providers existed."""
    h = hashlib.sha256()
    for part in (wav, (register_json or "").encode(), evaluate._tonekit_py_fingerprint().encode()):
        h.update(len(part).to_bytes(8, "big"))
        h.update(part)
    return h.hexdigest()


def test_without_a_provider_the_cache_key_is_what_it_always_was(
    corpus, pack_toml, calib_json, tmp_path
):
    root, clips = corpus
    evaluate.run(clips[:1], pack_toml, calib_json, None, root=root, cache_dir=tmp_path)
    (entry,) = tmp_path.glob("*.json")
    wav = (root / clips[0].path).read_bytes()
    assert entry.stem == old_cache_key(wav, None)
    assert evaluate._cache_key(wav, "{}") == old_cache_key(wav, "{}")


def test_f0_none_and_no_argument_are_the_same_run(corpus, pack_toml, calib_json):
    root, clips = corpus
    plain = evaluate.run(clips, pack_toml, calib_json, None, root=root, use_cache=False)
    explicit = evaluate.run(clips, pack_toml, calib_json, None, root=root, use_cache=False, f0=None)
    assert explicit == plain


def test_a_named_provider_hands_its_track_to_analyze_as_f0_json(
    corpus, pack_toml, calib_json, monkeypatch
):
    root, clips = corpus
    seen: list[str | None] = []
    real = evaluate.tonekit_py.analyze

    def spy(pcm, sample_rate, register_json=None, f0_json=None):
        seen.append(f0_json)
        return real(pcm, sample_rate, register_json, f0_json)

    monkeypatch.setattr(evaluate.tonekit_py, "analyze", spy)
    evaluate.run(clips[:1], pack_toml, calib_json, None, root=root, use_cache=False, f0="swift-f0")
    (f0_json,) = seen
    assert json.loads(f0_json)["provider"] == pitch_tracks.provider_identity("swift-f0")

    seen.clear()
    evaluate.run(clips[:1], pack_toml, calib_json, None, root=root, use_cache=False)
    assert seen == [None]  # pYIN: tonekit computes its own track


def test_swift_f0_grades_a_support_clip(corpus, pack_toml, calib_json):
    root, clips = corpus
    results = evaluate.run(
        clips, pack_toml, calib_json, None, root=root, use_cache=False, f0="swift-f0"
    )
    assert [r.id for r in results] == [c.id for c in clips]
    correct = [r for r in results if r.label == "correct"]
    assert all(r.overall is not None and 0.0 <= r.overall <= 1.0 for r in correct)
    assert all(s.measured != "NotMeasured" for r in correct for s in r.syllables)


def test_the_provider_joins_the_cache_key_and_its_entries_are_reused(
    corpus, pack_toml, calib_json, tmp_path, monkeypatch
):
    root, clips = corpus
    args = (clips[:1], pack_toml, calib_json, None)
    evaluate.run(*args, root=root, cache_dir=tmp_path)
    (pyin_entry,) = tmp_path.glob("*.json")
    swift = evaluate.run(*args, root=root, cache_dir=tmp_path, f0="swift-f0")
    entries = sorted(tmp_path.glob("*.json"))
    assert len(entries) == 2 and pyin_entry in entries  # one entry per provider for the same audio
    assert (
        json.loads(next(e for e in entries if e != pyin_entry).read_text())["f0"]["provider"]
        == "external"
    )

    def boom(*a, **k):
        raise AssertionError("the provider ran although its analysis is cached")

    monkeypatch.setattr(pitch_tracks, "provider_track", boom)
    monkeypatch.setattr(evaluate.tonekit_py, "analyze", boom)
    again = evaluate.run(*args, root=root, cache_dir=tmp_path, f0="swift-f0")
    assert again == swift


def test_the_cache_key_follows_the_providers_identity_not_just_its_name(corpus, monkeypatch):
    root, clips = corpus
    wav = (root / clips[0].path).read_bytes()
    before = evaluate._cache_key(wav, None, "swift-f0 0.3.0")
    assert before == evaluate._cache_key(wav, None, "swift-f0 0.3.0")
    assert before != evaluate._cache_key(wav, None, "swift-f0 0.4.0")
    assert before != evaluate._cache_key(wav, None)


def test_a_register_chain_uses_the_provider_too(tmp_path, pack_toml, calib_json):
    """A speaker's `register` clips are analysed with the provider as well, and give their other
    clips a given register."""
    clips = [
        make_clip(tmp_path, "reg-1", ["1", "2", "3"], set="register", label="n/a"),
        make_clip(tmp_path, "gate-a", ["4", "1", "3"], pair="p1"),
    ]
    results = evaluate.run(
        clips, pack_toml, calib_json, None, root=tmp_path, use_cache=False, f0="swift-f0"
    )
    assert [r.register_source for r in results] == ["cold", "given"]


def test_an_unknown_provider_is_an_error_naming_the_known_ones(corpus, pack_toml, calib_json):
    root, clips = corpus
    with pytest.raises(EvalError, match=r"unknown f0 provider 'crepe'.*swift-f0"):
        evaluate.run(clips[:1], pack_toml, calib_json, None, root=root, use_cache=False, f0="crepe")


def test_a_provider_failure_names_the_clip(tmp_path, pack_toml, calib_json, monkeypatch):
    clip = make_clip(tmp_path, "boom-clip", ["4", "1", "3"])

    def broken(name, pcm):
        raise ValueError("the model exploded")

    monkeypatch.setattr(pitch_tracks, "provider_track", broken)
    with pytest.raises(EvalError, match="boom-clip: the model exploded"):
        evaluate.run(
            [clip], pack_toml, calib_json, None, root=tmp_path, use_cache=False, f0="swift-f0"
        )
