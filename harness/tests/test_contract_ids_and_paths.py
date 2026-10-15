"""contracts.ids and contracts.relpath: the one card-id pattern and the one relative-path rule that
the deck, the bundle, the gate files and the corpus registry share."""

import pytest
from bundle_support import make_bundle, session_dict, wav_bytes
from pydantic import TypeAdapter, ValidationError
from test_deck import card, deck_dict, error_card
from test_gate import gate_dict
from test_registry import corpus_dict

from tonekit_harness.contracts.bundle import BundleError, Session, SessionClip, read_bundle
from tonekit_harness.contracts.deck import Deck
from tonekit_harness.contracts.gate import GateFile
from tonekit_harness.contracts.ids import CARD_ID_CHARS, CARD_ID_PATTERN, CardId
from tonekit_harness.contracts.registry import CorpusFile
from tonekit_harness.contracts.relpath import is_relative_inside

GOOD_IDS = ["g99-c", "a", "0", "d05-a", "x" * 40, "---", "9-9"]
BAD_IDS = ["G01-c", "g01_c", "g01 c", "", "g01-é", "g01.c", "g01/c", "../g01", "g01\n"]


@pytest.mark.parametrize("card_id", GOOD_IDS)
def test_good_ids_are_accepted_everywhere(card_id):
    assert TypeAdapter(CardId).validate_python(card_id) == card_id
    assert Deck.model_validate(deck_dict(card(id=card_id), error_card())).card[0].id == card_id
    clip = {"card": card_id, "file": f"clips/{card_id}.wav", "takes": 1, "duration_s": 0.1, "peak": 0.5}
    assert SessionClip.model_validate(clip).card == card_id
    assert Session.model_validate(session_dict(clips=[clip], skipped=[card_id + "-s"])).skipped == [card_id + "-s"]


@pytest.mark.parametrize("card_id", BAD_IDS)
def test_bad_ids_are_refused_everywhere(card_id):
    with pytest.raises(ValidationError):
        TypeAdapter(CardId).validate_python(card_id)
    with pytest.raises(ValidationError):
        Deck.model_validate(deck_dict(card(id=card_id), error_card()))
    with pytest.raises(ValidationError):
        SessionClip.model_validate(
            {"card": card_id, "file": f"clips/{card_id}.wav", "takes": 1, "duration_s": 0.1, "peak": 0.5}
        )
    with pytest.raises(ValidationError):
        Session.model_validate(session_dict(skipped=[card_id]))


def test_the_deck_and_pair_ids_follow_the_same_pattern():
    with pytest.raises(ValidationError, match="pair"):
        Deck.model_validate(deck_dict(card(pair="G01"), error_card()))
    with pytest.raises(ValidationError, match="deck.id"):
        Deck.model_validate(deck_dict() | {"deck": deck_dict()["deck"] | {"id": "S05"}})
    with pytest.raises(ValidationError, match="deck.id"):
        Session.model_validate(session_dict(deck={"id": "S05", "sha256": "ab" * 32}))


@pytest.mark.parametrize("card_id", GOOD_IDS + BAD_IDS)
def test_a_clip_member_name_is_built_from_the_card_id_pattern(tmp_path, card_id):
    """`clips/<id>.wav` is an expected member exactly when <id> is a card id."""
    path = make_bundle(tmp_path / "b.zip", extra={f"clips/{card_id}.wav": wav_bytes()})
    with pytest.raises(BundleError) as e:
        read_bundle(path)
    out = str(e.value)
    if card_id in GOOD_IDS:
        assert f"clips/{card_id}.wav is in the zip but not listed in session.json" in out
    else:
        assert f"unexpected file {f'clips/{card_id}.wav'!r}" in out


def test_the_pattern_and_its_body_agree():
    assert CARD_ID_PATTERN == f"^{CARD_ID_CHARS}$"


# ---- one relative-path rule ------------------------------------------------------------------


@pytest.mark.parametrize("path", ["a", "a/b.json", "./a", "a//b", "reports/p1-latency.json", "ünï.json"])
def test_relative_paths_inside(path):
    assert is_relative_inside(path)


@pytest.mark.parametrize("path", ["", ".", "./", "/abs", "/", "..", "../x", "a/../b", "a/b/..", "a/.."])
def test_other_paths_are_refused(path):
    assert not is_relative_inside(path)


@pytest.mark.parametrize("path", ["", ".", "/abs/x.json", "../x.json", "a/../../x.json"])
def test_the_gate_input_file_uses_the_rule(path):
    data = gate_dict(input=[{"metric": "latency_p95_ms", "file": path}])
    with pytest.raises(ValidationError, match="must be a relative path with no '..'"):
        GateFile.model_validate(data)


@pytest.mark.parametrize("path", ["", ".", "/abs/m.jsonl", "../m.jsonl", "a/../../m.jsonl"])
def test_the_corpus_manifest_uses_the_rule(path):
    data = corpus_dict()
    data["corpus"]["manifest"] = path
    with pytest.raises(ValidationError, match="must be a relative path inside the corpus directory"):
        CorpusFile.model_validate(data)


@pytest.mark.parametrize("path", ["reports/p1.json", "./p1.json"])
def test_both_accept_what_the_rule_accepts(path):
    GateFile.model_validate(gate_dict(input=[{"metric": "latency_p95_ms", "file": path}]))
    data = corpus_dict()
    data["corpus"]["manifest"] = path
    assert CorpusFile.model_validate(data).corpus.manifest == path
