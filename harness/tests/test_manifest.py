import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tonekit_harness import manifest
from tonekit_harness.manifest import Candidate, Clip, ManifestError


def row(**overrides) -> dict:
    base = {
        "id": "gate-01-correct",
        "path": "dj/gate-01-correct.wav",
        "speaker": "dj",
        "set": "gate",
        "pair": "gate-01",
        "label": "correct",
        "intended": {"id": "yi4bei1shui3", "tones": ["4", "1", "3"], "labels": ["4", "1", "3"]},
        "distractors": [{"id": "yi4bei2shui3", "tones": ["4", "2", "3"], "labels": []}],
        "produced_tones": ["4", "1", "3"],
        "condition": {"noise": "cafe", "distance": "arm"},
        "source": "dj-corpus",
        "synthetic": None,
        "needs_listen": False,
    }
    base.update(overrides)
    return base


def write_jsonl(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_valid_row_parses():
    c = Clip.model_validate(row())
    assert c.id == "gate-01-correct"
    assert c.set == "gate"
    assert c.label == "correct"
    assert c.intended == Candidate(id="yi4bei1shui3", tones=["4", "1", "3"], labels=["4", "1", "3"])
    assert c.distractors[0].id == "yi4bei2shui3"
    assert c.condition.noise == "cafe" and c.condition.distance == "arm"
    assert c.source == "dj-corpus"
    assert c.synthetic is None
    assert c.needs_listen is False


def test_row_missing_intended_fails_validation():
    r = row()
    del r["intended"]
    with pytest.raises(ValidationError) as e:
        Clip.model_validate(r)
    assert "intended" in str(e.value)


@pytest.mark.parametrize("field", ["id", "path", "speaker", "set", "label", "condition", "source"])
def test_other_required_fields(field):
    r = row()
    del r[field]
    with pytest.raises(ValidationError):
        Clip.model_validate(r)


def test_optional_fields_default():
    r = row()
    for k in ("pair", "produced_tones", "synthetic", "needs_listen", "distractors"):
        del r[k]
    c = Clip.model_validate(r)
    assert c.pair is None
    assert c.produced_tones is None
    assert c.synthetic is None
    assert c.needs_listen is False
    assert c.distractors == []


@pytest.mark.parametrize("s", ["gate", "diag_t23", "diag_count", "diag_minimal", "quiet", "register", "synthetic"])
def test_every_set_is_accepted(s):
    assert Clip.model_validate(row(set=s)).set == s


@pytest.mark.parametrize("l", ["correct", "tone_error", "graded", "n/a"])
def test_every_label_is_accepted(l):
    assert Clip.model_validate(row(label=l)).label == l


def test_unknown_set_and_label_rejected():
    with pytest.raises(ValidationError):
        Clip.model_validate(row(set="dev"))
    with pytest.raises(ValidationError):
        Clip.model_validate(row(label="wrong"))


def test_unknown_field_rejected():
    # a typo like "distractor" must not silently drop the distractors
    with pytest.raises(ValidationError):
        Clip.model_validate(row(distractor=[]))


def test_synthetic_carries_free_form_dict():
    c = Clip.model_validate(row(set="synthetic", synthetic={"from": "gate-01-correct", "f0_scale": 1.1}))
    assert c.synthetic == {"from": "gate-01-correct", "f0_scale": 1.1}


def test_candidate_labels_longer_than_tones_rejected():
    with pytest.raises(ValidationError):
        Candidate(id="x", tones=["1"], labels=["1", "2"])


def test_to_candidate_json_pads_missing_labels_with_null():
    c = Candidate(id="yi4bei1shui3", tones=["4", "1", "3"], labels=["4"])
    assert json.loads(manifest.to_candidate_json(c)) == {
        "id": "yi4bei1shui3",
        "targets": [
            {"tone": "4", "lexical_variants": [], "label": "4"},
            {"tone": "1", "lexical_variants": [], "label": None},
            {"tone": "3", "lexical_variants": [], "label": None},
        ],
    }


def test_to_candidate_json_empty_label_is_null_and_no_labels_ok():
    c = Candidate(id="a", tones=["2", "3"], labels=["", "3"])
    targets = json.loads(manifest.to_candidate_json(c))["targets"]
    assert [t["label"] for t in targets] == [None, "3"]
    c = Candidate(id="b", tones=["5"], labels=[])
    assert json.loads(manifest.to_candidate_json(c))["targets"][0]["label"] is None


def test_load_reads_jsonl_and_skips_blank_lines(tmp_path):
    p = write_jsonl(
        tmp_path / "m.jsonl",
        [json.dumps(row(id="a")), "", "   ", json.dumps(row(id="b")), ""],
    )
    clips = manifest.load(p)
    assert [c.id for c in clips] == ["a", "b"]
    assert all(isinstance(c, Clip) for c in clips)


def test_load_accepts_str_path(tmp_path):
    p = write_jsonl(tmp_path / "m.jsonl", [json.dumps(row())])
    assert len(manifest.load(str(p))) == 1


def test_load_reports_line_number_for_invalid_row(tmp_path):
    bad = row(id="bad")
    del bad["intended"]
    p = write_jsonl(tmp_path / "m.jsonl", [json.dumps(row(id="a")), "", json.dumps(bad)])
    with pytest.raises(ManifestError) as e:
        manifest.load(p)
    assert ":3:" in str(e.value)
    assert "intended" in str(e.value)


def test_load_reports_line_number_for_malformed_json(tmp_path):
    p = write_jsonl(tmp_path / "m.jsonl", [json.dumps(row()), "{not json"])
    with pytest.raises(ManifestError) as e:
        manifest.load(p)
    assert ":2:" in str(e.value)


def test_load_rejects_non_object_row(tmp_path):
    p = write_jsonl(tmp_path / "m.jsonl", ["[1, 2]"])
    with pytest.raises(ManifestError) as e:
        manifest.load(p)
    assert ":1:" in str(e.value)
