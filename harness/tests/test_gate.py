"""contracts.gate: gates/<id>.toml (contracts.md section 5)."""

import pytest
from pydantic import ValidationError

from tonekit_harness.contracts.gate import GateError, GateFile, load_gate, parse_gate

METRICS = {"correct_accept", "wrong_accept", "candidate_id_accuracy", "count_robustness", "t23_confusion"}

EXAMPLE = """\
[gate]
id = "s1"
phase = "p0"
summary = "Tone errors are told apart from correct readings on real speech"

[select]
corpora = ["*"]
kinds = ["recorded"]
splits = ["gate"]
sets = ["gate"]

[thresholds]
method = "loso"

[[criterion]]
metric = "correct_accept"
min = 0.90

[[criterion]]
metric = "wrong_accept"
max = 0.10

[requires]
speakers_min = 1
l1_min = 1

[report]
by = ["speaker", "background", "grew_up_hearing", "context"]
diagnostics = ["candidate_id_accuracy", "count_robustness", "t23_confusion"]
"""

LATENCY_INPUT = {"metric": "latency_p95_ms", "file": "reports/p1-latency.json", "summary": "iPhone 12 latency"}
PATHS_CHECK = {
    "id": "no-engine-diff", "kind": "paths_unchanged", "base": "p1-final",
    "paths": [".", ":(exclude)packs", ":(exclude)harness/src/tonekit_harness/calibration.py"],
}


def gate_dict(**overrides) -> dict:
    base = {
        "gate": {"id": "s1", "phase": "p0", "summary": "Tone errors are told apart"},
        "select": {"corpora": ["*"], "kinds": ["recorded"], "splits": ["gate"], "sets": ["gate"]},
        "thresholds": {"method": "loso"},
        "criterion": [{"metric": "correct_accept", "min": 0.9}, {"metric": "wrong_accept", "max": 0.1}],
    }
    return base | overrides


def problems(data: dict, known=METRICS) -> str:
    with pytest.raises(GateError) as e:
        parse_gate(data, known_metrics=known)
    return str(e.value)


def test_the_contracts_example_loads(tmp_path):
    path = tmp_path / "s1.toml"
    path.write_text(EXAMPLE, encoding="utf-8")
    gate = load_gate(path, known_metrics=METRICS)
    assert gate.gate.id == "s1" and gate.thresholds.method == "loso"
    assert [(c.metric, c.min, c.max) for c in gate.criterion] == [
        ("correct_accept", 0.9, None), ("wrong_accept", None, 0.1)
    ]
    assert gate.select.corpora == ["*"] and gate.select.splits == ["gate"]
    assert gate.requires.speakers_min == 1 and gate.report.by[-1] == "context"
    assert gate.report.diagnostics == ["candidate_id_accuracy", "count_robustness", "t23_confusion"]


def test_only_gate_select_thresholds_and_criteria_are_required():
    gate = parse_gate(gate_dict(), known_metrics=METRICS)
    assert (gate.requires.speakers_min, gate.requires.l1_min) == (1, 1)
    assert gate.report.by == [] and gate.report.diagnostics == [] and gate.input == [] and gate.check == []


def test_load_errors_name_the_file(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text(EXAMPLE.replace('method = "loso"', 'method = "kfold"'), encoding="utf-8")
    with pytest.raises(GateError, match=r"bad\.toml.*\n.*thresholds\.method"):
        load_gate(path, known_metrics=METRICS)


def test_invalid_toml_names_the_file(tmp_path):
    path = tmp_path / "bad.toml"
    path.write_text("[gate\n", encoding="utf-8")
    with pytest.raises(GateError, match="bad.toml: invalid TOML"):
        load_gate(path, known_metrics=METRICS)


@pytest.mark.parametrize("method", ["loso", "lopo"])
def test_both_threshold_methods_are_accepted(method):
    assert parse_gate(gate_dict(thresholds={"method": method}), known_metrics=METRICS).thresholds.method == method


# ---- criteria -----------------------------------------------------------------------------


def test_a_criterion_has_a_min_or_a_max():
    for crit in ({"metric": "correct_accept", "min": 0.9}, {"metric": "wrong_accept", "max": 0.1}):
        assert parse_gate(gate_dict(criterion=[crit]), known_metrics=METRICS).criterion[0].metric == crit["metric"]


def test_a_criterion_with_both_min_and_max_is_refused():
    out = problems(gate_dict(criterion=[{"metric": "correct_accept", "min": 0.9, "max": 0.99}]))
    assert "criterion 'correct_accept': needs exactly one of min and max, got both" in out


def test_a_criterion_with_neither_is_refused():
    out = problems(gate_dict(criterion=[{"metric": "correct_accept"}]))
    assert "criterion 'correct_accept': needs exactly one of min and max, got neither" in out


def test_a_gate_needs_a_criterion():
    assert "at least 1 item" in problems(gate_dict(criterion=[]))


def test_a_threshold_that_is_not_a_number_names_the_criterion():
    assert "criterion 'correct_accept'.min" in problems(gate_dict(criterion=[{"metric": "correct_accept", "min": "high"}]))


# ---- metric names -------------------------------------------------------------------------


def test_an_unknown_metric_is_an_error_with_a_suggestion():
    out = problems(gate_dict(criterion=[{"metric": "corect_accept", "min": 0.9}]))
    assert "unknown metric 'corect_accept' in [[criterion]] (did you mean 'correct_accept'?)" in out


def test_an_unknown_metric_with_no_close_match_lists_the_known_ones():
    out = problems(gate_dict(criterion=[{"metric": "zzz", "min": 0.9}]))
    assert "unknown metric 'zzz'" in out and "known: candidate_id_accuracy" in out


def test_diagnostics_are_metrics_too():
    out = problems(gate_dict(report={"diagnostics": ["t23_confusion", "nope"]}))
    assert "unknown metric 'nope' in [report] diagnostics" in out


def test_a_metric_measured_elsewhere_names_an_input():
    data = gate_dict(
        criterion=[{"metric": "latency_p95_ms", "max": 150}], input=[LATENCY_INPUT],
    )
    gate = parse_gate(data, known_metrics=METRICS)
    assert gate.input[0].file == "reports/p1-latency.json"


def test_the_metric_registry_is_required_by_the_loaders(tmp_path):
    with pytest.raises(TypeError):
        parse_gate(gate_dict())  # type: ignore[call-arg]


def test_the_bare_model_checks_structure_but_not_metric_names():
    gate = GateFile.model_validate(gate_dict(criterion=[{"metric": "anything", "min": 1}]))
    assert gate.criterion[0].metric == "anything"


# ---- select, requires, report -------------------------------------------------------------


@pytest.mark.parametrize("field,value", [
    ("corpora", []), ("kinds", []), ("splits", []), ("sets", []),
    ("kinds", ["live"]), ("splits", ["train"]), ("sets", ["gates"]), ("corpora", [""]),
])
def test_select_fields_are_checked(field, value):
    select = gate_dict()["select"] | {field: value}
    assert f"select.{field}" in problems(gate_dict(select=select))


def test_a_gate_refuses_synthetic_corpora():
    select = gate_dict()["select"] | {"kinds": ["recorded", "synthetic"]}
    assert "select.kinds: a gate refuses synthetic corpora" in problems(gate_dict(select=select))


def test_every_other_kind_and_split_can_be_selected():
    select = {"corpora": ["a*", "b"], "kinds": ["recorded", "public"], "splits": ["gate", "heldout", "dev", "calib"],
              "sets": ["gate", "diag_t23", "diag_count", "diag_minimal", "register", "quiet"]}
    assert parse_gate(gate_dict(select=select), known_metrics=METRICS).select.corpora == ["a*", "b"]


@pytest.mark.parametrize("field", ["speakers_min", "l1_min"])
@pytest.mark.parametrize("value", [0, -1])
def test_requires_are_at_least_one(field, value):
    assert f"requires.{field}" in problems(gate_dict(requires={field: value}))


def test_report_by_is_an_enum():
    assert "report.by.0" in problems(gate_dict(report={"by": ["shoe_size"]}))


@pytest.mark.parametrize("field,value", [("id", "S1"), ("id", ""), ("phase", ""), ("summary", "")])
def test_gate_meta_fields(field, value):
    assert f"gate.{field}" in problems(gate_dict(gate=gate_dict()["gate"] | {field: value}))


# ---- inputs and checks --------------------------------------------------------------------


@pytest.mark.parametrize("file", ["/abs/x.json", "../x.json", "a/../../x.json", ""])
def test_an_input_file_is_a_relative_path(file):
    assert "input 'latency_p95_ms'" in problems(gate_dict(input=[LATENCY_INPUT | {"file": file}]))


def test_an_input_metric_is_named_once():
    assert "input metric 'latency_p95_ms' appears more than once" in problems(
        gate_dict(input=[LATENCY_INPUT, LATENCY_INPUT])
    )


def test_a_paths_unchanged_check():
    gate = parse_gate(gate_dict(check=[PATHS_CHECK]), known_metrics=METRICS)
    check = gate.check[0]
    assert (check.kind, check.base, check.paths[1]) == ("paths_unchanged", "p1-final", ":(exclude)packs")


@pytest.mark.parametrize("change", [{"base": ""}, {"paths": []}, {"id": "Bad Id"}, {"kind": "tests_pass"}])
def test_check_fields_are_checked(change):
    out = problems(gate_dict(check=[PATHS_CHECK | change]))
    assert "check" in out and next(iter(change)) in out


def test_check_ids_are_unique():
    assert "check 'no-engine-diff' appears more than once" in problems(gate_dict(check=[PATHS_CHECK, PATHS_CHECK]))


@pytest.mark.parametrize("where", ["top", "gate", "select", "thresholds", "requires", "report"])
def test_unknown_keys_are_errors(where):
    data = gate_dict(requires={}, report={})
    (data if where == "top" else data[where])["typo"] = 1
    assert "typo" in problems(data)


def test_a_gate_model_is_not_a_pydantic_error_to_callers():
    with pytest.raises(ValidationError):
        GateFile.model_validate(gate_dict(thresholds={"method": "kfold"}))
