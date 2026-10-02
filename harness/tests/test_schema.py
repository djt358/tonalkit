"""`tkh schema`: the JSON Schemas of the S0.5 formats, for the kit's JavaScript tests."""

import json

import pytest

from tonekit_harness import cli, schema
from tonekit_harness.contracts.bundle import SESSION_CODE_PATTERN
from tonekit_harness.repo import repo_root

FILES = ["corpus.schema.json", "deck.schema.json", "gate.schema.json", "session.schema.json"]


def test_every_format_gets_a_schema_file(tmp_path):
    written = schema.write_schemas(tmp_path)
    assert sorted(p.name for p in written) == FILES
    for path in written:
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert doc["type"] == "object" and doc["additionalProperties"] is False


def test_the_output_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    schema.write_schemas(a)
    schema.write_schemas(b)
    for name in FILES:
        assert (a / name).read_bytes() == (b / name).read_bytes()
        text = (a / name).read_text(encoding="utf-8")
        assert text.endswith("}\n") and text == json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_the_session_schema_carries_the_contract(tmp_path):
    doc = json.loads(schema.write_schemas(tmp_path)[FILES.index("session.schema.json")].read_text(encoding="utf-8"))
    assert doc["properties"]["schema"]["const"] == "tonekit.session.v1"
    assert doc["properties"]["session"]["pattern"] == SESSION_CODE_PATTERN
    assert set(doc["required"]) >= {"schema", "deck", "session", "consent", "speaker", "device", "clips"}
    speaker = doc["$defs"]["SpeakerInfo"]["properties"]
    assert speaker["background"]["enum"] == ["native", "heritage", "learner", "prefer_not"]


def test_the_deck_schema_carries_the_card_vocabulary(tmp_path):
    written = {p.name: p for p in schema.write_schemas(tmp_path)}
    doc = json.loads(written["deck.schema.json"].read_text(encoding="utf-8"))
    card = doc["$defs"]["Card"]["properties"]
    assert card["set"]["enum"] == [
        "gate", "diag_t23", "diag_count", "diag_minimal", "diag_context", "quiet", "register"
    ]
    assert card["label"]["enum"] == ["correct", "tone_error", "n/a"]
    assert card["context"]["enum"] == ["phrase", "isolated"]


def test_the_committed_schemas_are_current(tmp_path):
    schema.write_schemas(tmp_path)
    committed = repo_root() / "kit" / "schema"
    for name in FILES:
        assert (committed / name).read_text(encoding="utf-8") == (tmp_path / name).read_text(encoding="utf-8"), (
            f"kit/schema/{name} is stale: run `uv run tkh schema` and commit the result"
        )
    assert sorted(p.name for p in committed.iterdir()) == FILES


def test_the_default_output_is_kit_schema_in_the_repository():
    assert schema.default_out_dir() == repo_root() / "kit" / "schema"


def test_the_command_writes_to_out_and_says_what(tmp_path, capsys):
    assert cli.main(["schema", "--out", str(tmp_path / "s")]) == 0
    out = capsys.readouterr().out
    assert all(name in out for name in FILES)
    assert sorted(p.name for p in (tmp_path / "s").iterdir()) == FILES


def test_the_command_is_listed(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "schema" in capsys.readouterr().out
