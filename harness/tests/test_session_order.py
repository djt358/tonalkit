"""The order each speaker read their clips in (ruling R111): `session_order`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bundle_support import session_dict
from support import make_clip

from tonekit_harness.manifest import Clip
from tonekit_harness.session_order import SessionOrderError, reading_order, session_code


def recorded(root: Path, code: str, card: str, *, speaker: str = "v-k7q2md", set: str = "gate") -> Clip:
    """A clip as intake writes it: id `<CODE>-<card>`, `card` set (the audio is synthetic)."""
    clip = make_clip(root, f"{code}-{card}", ["1", "4"], set=set, speaker=speaker)
    return clip.model_copy(update={"card": card})


def write_session(root: Path, code: str, cards: list[str], started_at: str = "2026-10-03T18:02:11Z") -> None:
    clips = [{"card": c, "file": f"clips/{c}.wav", "takes": 1, "duration_s": 1.0, "peak": 0.5} for c in cards]
    doc = session_dict(session=code, clips=clips, skipped=[], started_at=started_at, finished_at="2026-10-04T00:00:00Z")
    (root / "sessions").mkdir(exist_ok=True)
    (root / "sessions" / f"{code}.json").write_text(json.dumps(doc), encoding="utf-8")


def test_the_session_code_is_the_id_before_the_card():
    assert session_code(Clip.model_validate({**_row("K7Q2MD-g01-c"), "card": "g01-c"})) == "K7Q2MD"
    assert session_code(Clip.model_validate({**_row("K7Q2MD-g01-c"), "card": None})) is None
    assert session_code(Clip.model_validate({**_row("other-name"), "card": "g01-c"})) is None


def _row(cid: str) -> dict:
    return {
        "id": cid, "path": f"{cid}.wav", "speaker": "s", "set": "gate", "label": "correct",
        "intended": {"id": "x", "tones": ["1"], "labels": []},
        "condition": {"noise": "none", "distance": "synthetic"}, "source": "synthetic-world",
    }  # fmt: skip


def test_clips_follow_the_session_files_reading_order(tmp_path):
    cards = ["r01", "g01-c", "g01-e", "g02-c"]
    clips = [recorded(tmp_path, "K7Q2MD", c) for c in cards]
    write_session(tmp_path, "K7Q2MD", ["r01", "g02-c", "g01-e", "g01-c"])
    got = reading_order(clips, tmp_path)
    assert [c.card for c in got["v-k7q2md"]] == ["r01", "g02-c", "g01-e", "g01-c"]


def test_a_speakers_sessions_are_ordered_by_their_start(tmp_path):
    late = [recorded(tmp_path, "BBBBBB", "g01-c"), recorded(tmp_path, "BBBBBB", "g01-e")]
    early = [recorded(tmp_path, "AAAAAA", "g02-e"), recorded(tmp_path, "AAAAAA", "g02-c")]
    write_session(tmp_path, "BBBBBB", ["g01-e", "g01-c"], started_at="2026-10-03T20:00:00Z")
    write_session(tmp_path, "AAAAAA", ["g02-c", "g02-e"], started_at="2026-10-03T08:00:00Z")
    got = reading_order([*late, *early], tmp_path)["v-k7q2md"]
    assert [c.id for c in got] == ["AAAAAA-g02-c", "AAAAAA-g02-e", "BBBBBB-g01-e", "BBBBBB-g01-c"]


def test_without_a_session_file_a_speaker_keeps_manifest_order(tmp_path):
    clips = [recorded(tmp_path, "K7Q2MD", c) for c in ["g02-c", "g01-c"]]
    other = [make_clip(tmp_path, f"plain-{i}", ["1"], speaker="dj") for i in range(2)]
    got = reading_order([*clips, *other], tmp_path)
    assert [c.card for c in got["v-k7q2md"]] == ["g02-c", "g01-c"]
    assert [c.id for c in got["dj"]] == ["plain-0", "plain-1"]
    assert list(got) == ["v-k7q2md", "dj"]  # speakers in manifest order


def test_a_card_missing_from_its_session_file_falls_back_to_manifest_order(tmp_path):
    clips = [recorded(tmp_path, "K7Q2MD", c) for c in ["g02-c", "g01-c"]]
    write_session(tmp_path, "K7Q2MD", ["g01-c"])
    assert [c.card for c in reading_order(clips, tmp_path)["v-k7q2md"]] == ["g02-c", "g01-c"]


def test_an_unreadable_session_file_is_an_error(tmp_path):
    clips = [recorded(tmp_path, "K7Q2MD", "g01-c")]
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "K7Q2MD.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SessionOrderError, match="K7Q2MD.json"):
        reading_order(clips, tmp_path)
