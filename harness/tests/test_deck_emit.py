"""deck_build.emit: the contract file and the kit's JSON, deterministic and in the model's shape."""

import json
import tomllib

from deck_support import needs_c0_fix, small_deck_data

from tonekit_harness.contracts.deck import load_deck
from tonekit_harness.deck_build import contract_view
from tonekit_harness.deck_build.contract_view import contract_card
from tonekit_harness.deck_build.emit import json_text, toml_text, write_deck

pytestmark = needs_c0_fix


def test_the_toml_reads_back_as_the_same_cards():
    data = small_deck_data()
    back = tomllib.loads(toml_text(data))
    assert back["deck"] == data["deck"]
    assert back["card"] == [contract_card(c) for c in data["card"]]


def test_strings_with_quotes_backslashes_and_hanzi_survive_the_toml():
    data = small_deck_data(1)
    data["card"][0]["prompt_note"] = 'Say "um", then \\ pause…\tand 一杯水.'
    assert tomllib.loads(toml_text(data))["card"][0]["prompt_note"] == data["card"][0]["prompt_note"]


def test_the_json_is_the_same_cards_in_the_same_key_order_with_a_final_newline():
    data = small_deck_data()
    text = json_text(data)
    assert text.endswith("}\n") and not text.endswith("\n\n")
    back = json.loads(text)
    assert back == data
    assert list(back["card"][1]) == list(data["card"][1])  # id, set, pair, label, text, ...
    assert list(back["card"][1])[:5] == ["id", "set", "pair", "label", "text"]
    assert "一杯水" in text  # not \u-escaped: the file is read by people too


def test_writing_makes_both_files_the_same_bytes_every_time(tmp_path):
    data = small_deck_data()
    paths = write_deck(data, tmp_path / "out")
    assert [p.name for p in paths] == ["t-v1.toml", "t-v1.json"]
    first = [p.read_bytes() for p in paths]
    write_deck(data, tmp_path / "out")
    assert [p.read_bytes() for p in paths] == first
    assert all(b"\r" not in b and not b.startswith(b"\xef\xbb\xbf") for b in first)


def test_the_written_toml_loads_clean(tmp_path):
    toml_path, _ = write_deck(small_deck_data(), tmp_path)
    deck = load_deck(toml_path)
    assert [c.id for c in deck.card] == ["r01", "g01-c", "g01-e", "g02-c", "g02-e"]
    assert {c.status for c in deck.card} == {"unverified"}


def test_a_field_the_model_cannot_hold_yet_stays_in_the_json_and_out_of_the_toml(tmp_path, monkeypatch):
    monkeypatch.setattr(contract_view, "dropped_fields", lambda: ["text_traditional", "prompt_note_traditional"])
    data = small_deck_data()
    toml_path, json_path = write_deck(data, tmp_path)
    in_toml = tomllib.loads(toml_path.read_text(encoding="utf-8"))["card"]
    in_json = json.loads(json_path.read_text(encoding="utf-8"))["card"]
    assert all("text_traditional" not in c and "prompt_note_traditional" not in c for c in in_toml)
    assert all("text_traditional" in c for c in in_json)
    assert [c["id"] for c in in_json if "prompt_note_traditional" in c] == ["g01-e", "g02-e"]
    load_deck(toml_path)  # the contract file is clean either way


def test_the_traditional_note_follows_the_note_in_the_toml_and_the_json(tmp_path):
    toml_path, json_path = write_deck(small_deck_data(), tmp_path)
    (error,) = [c for c in tomllib.loads(toml_path.read_text(encoding="utf-8"))["card"] if c["id"] == "g02-e"]
    assert list(error)[-3:] == ["prompt_note", "prompt_note_traditional", "status"]
    assert error["prompt_note_traditional"] == "Read it as written: 樹 as in 大樹 (tree)."
    assert load_deck(toml_path).card[4].prompt_note_traditional == error["prompt_note_traditional"]
