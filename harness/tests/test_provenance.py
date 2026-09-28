import csv
from pathlib import Path

import pytest

from tonekit_harness import cli, provenance

HERE = Path(__file__).parent
FIX = HERE / "fixtures"
REPO = HERE.parents[1]
REAL_REGISTER = REPO / "data-register.csv"
REGISTER = FIX / "register.csv"  # trimmed copy of data-register.csv with the columns check() reads

ZERO = FIX / "provenance_zero_source.toml"
MAGICDATA = FIX / "provenance_magicdata_deny.toml"
OMPAL_UNSIGNED = FIX / "provenance_ompal_unsigned.toml"
OMPAL_SIGNED = FIX / "provenance_ompal_signed.toml"
AISHELL3 = FIX / "provenance_aishell3_allow.toml"

HEADER = 'artifact = "packs/x/x.calib.json"\nnote = "test"\n'


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def write_body(tmp_path: Path, name: str, body: str) -> Path:
    """A manifest with a valid artifact/note header followed by `body`."""
    return write(tmp_path, name, HEADER + body)


def test_zero_source_manifest_passes():
    assert provenance.check(REGISTER, [ZERO]) == []


def test_allow_source_passes():
    assert provenance.check(REGISTER, [AISHELL3]) == []


def test_deny_source_is_flagged():
    v = provenance.check(REGISTER, [MAGICDATA])
    assert len(v) == 1
    assert "source 'magicdata-read' is deny" in v[0]
    assert MAGICDATA.name in v[0]


def test_verify_without_signoff_is_flagged():
    v = provenance.check(REGISTER, [OMPAL_UNSIGNED])
    assert len(v) == 1
    assert "source 'ompal' is verify and has no matching [[signoff]]" in v[0]


def test_verify_with_matching_signoff_passes():
    assert provenance.check(REGISTER, [OMPAL_SIGNED]) == []


def test_signoff_for_a_different_id_does_not_count(tmp_path):
    p = write_body(
        tmp_path,
        "p.toml",
        '[[source]]\nid = "ompal"\n[[signoff]]\nid = "mfa-mandarin"\nby = "DJ"\ndate = "2026-09-28"\n',
    )
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "ompal" in v[0]


def test_signoff_never_overrides_deny(tmp_path):
    p = write_body(
        tmp_path,
        "p.toml",
        '[[source]]\nid = "magicdata-read"\n[[signoff]]\nid = "magicdata-read"\nby = "DJ"\ndate = "2026-09-28"\n',
    )
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "source 'magicdata-read' is deny" in v[0]


def test_unknown_source_id_is_flagged(tmp_path):
    p = write_body(tmp_path, "p.toml", '[[source]]\nid = "made-up"\n')
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "source 'made-up' is unknown" in v[0]


def test_na_source_is_flagged(tmp_path):
    p = write_body(tmp_path, "p.toml", '[[source]]\nid = "pyin"\n')
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "source 'pyin' is n/a" in v[0]


def test_unrecognised_register_value_is_flagged(tmp_path):
    reg = write(
        tmp_path,
        "reg.csv",
        "id,shipped_weights_training\nweird,maybe\nblank,\n",
    )
    p = write_body(tmp_path, "p.toml", '[[source]]\nid = "weird"\n[[source]]\nid = "blank"\n')
    v = provenance.check(reg, [p])
    assert len(v) == 2
    assert "source 'weird' has unrecognised" in v[0] and "'maybe'" in v[0]
    assert "source 'blank' has unrecognised" in v[1]


def test_every_violation_is_reported_across_manifests():
    v = provenance.check(REGISTER, [MAGICDATA, ZERO, OMPAL_UNSIGNED, AISHELL3])
    assert len(v) == 2
    assert "magicdata-read" in v[0] and "ompal" in v[1]


def test_multiple_violations_in_one_manifest(tmp_path):
    p = write_body(
        tmp_path,
        "p.toml",
        '[[source]]\nid = "magicdata-read"\n[[source]]\nid = "ompal"\n[[source]]\nid = "aishell-3"\n',
    )
    assert len(provenance.check(REGISTER, [p])) == 2


def test_same_file_listed_twice_is_checked_once():
    assert len(provenance.check(REGISTER, [MAGICDATA, MAGICDATA])) == 1


def test_missing_manifest_is_a_violation(tmp_path):
    v = provenance.check(REGISTER, [tmp_path / "packs" / "*" / "PROVENANCE.toml"])
    assert len(v) == 1 and "PROVENANCE.toml" in v[0]


def test_malformed_toml_is_a_violation(tmp_path):
    p = write(tmp_path, "p.toml", "[[source]\nid = ")
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "p.toml" in v[0]


@pytest.mark.parametrize(
    "body",
    [
        '[source]\nid = "aishell-3"\n',  # single table instead of [[source]]
        "source = [1, 2]\n",
        '[[source]]\nuse = "no id"\n',
        "[[source]]\nid = 7\n",
        'signoff = "DJ"\n',
        '[[signoff]]\nby = "DJ"\n',  # signoff without id
    ],
)
def test_structurally_invalid_manifest_is_a_violation(tmp_path, body):
    v = provenance.check(REGISTER, [write_body(tmp_path, "p.toml", body)])
    assert len(v) >= 1


def test_register_without_required_columns_raises(tmp_path):
    reg = write(tmp_path, "reg.csv", "id,license\naishell-3,Apache-2.0\n")
    with pytest.raises(provenance.ProvenanceError):
        provenance.check(reg, [ZERO])


def test_duplicate_register_ids_raise(tmp_path):
    reg = write(tmp_path, "reg.csv", "id,shipped_weights_training\na,allow\na,deny\n")
    with pytest.raises(provenance.ProvenanceError):
        provenance.check(reg, [ZERO])


# --- strict format: a typo must never look like a clean zero-source file -------------------


@pytest.mark.parametrize(
    "table, sid",
    [("sources", "magicdata-read"), ("Source", "mms"), ("SOURCE", "magicdata-read"), ("signoffs", "ompal")],
)
def test_misspelt_table_name_is_a_violation(tmp_path, table, sid):
    # against the real register: these used to return [] and pass the licence gate
    p = write_body(tmp_path, "p.toml", f'[[{table}]]\nid = "{sid}"\n')
    v = provenance.check(REAL_REGISTER, [p])
    assert len(v) == 1
    assert f"unknown top-level key '{table}'" in v[0]


def test_misspelt_table_name_gets_a_hint(tmp_path):
    p = write_body(tmp_path, "p.toml", '[[sources]]\nid = "magicdata-read"\n')
    assert "did you mean 'source'" in provenance.check(REAL_REGISTER, [p])[0]


def test_unknown_top_level_scalar_key_is_a_violation(tmp_path):
    p = write(tmp_path, "p.toml", HEADER + 'owner = "DJ"\n')
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "unknown top-level key 'owner'" in v[0]


def test_empty_manifest_is_a_violation(tmp_path):
    p = write(tmp_path, "PROVENANCE.toml", "")
    v = provenance.check(REAL_REGISTER, [p])
    assert len(v) == 2
    assert any("missing required key `artifact`" in x for x in v)
    assert any("missing required key `note`" in x for x in v)


def test_comment_only_manifest_is_a_violation(tmp_path):
    assert len(provenance.check(REAL_REGISTER, [write(tmp_path, "p.toml", "# nothing here\n")])) == 2


@pytest.mark.parametrize("key", ["artifact", "note"])
def test_missing_artifact_or_note_is_a_violation(tmp_path, key):
    other = "note" if key == "artifact" else "artifact"
    p = write(tmp_path, "p.toml", f'{other} = "x"\n')
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and f"missing required key `{key}`" in v[0]


@pytest.mark.parametrize("key", ["artifact", "note"])
@pytest.mark.parametrize("value", ['""', '"   "', "7", "[]", "true"])
def test_empty_or_non_string_artifact_or_note_is_a_violation(tmp_path, key, value):
    other = "note" if key == "artifact" else "artifact"
    p = write(tmp_path, "p.toml", f'{other} = "x"\n{key} = {value}\n')
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and f"`{key}` must be a non-empty string" in v[0]


@pytest.mark.parametrize("by", ["", '"   "', "7"])
def test_signoff_without_a_real_by_is_a_violation(tmp_path, by):
    by_line = "" if by == "" else f"by = {by}\n"
    p = write_body(
        tmp_path,
        "p.toml",
        f'[[source]]\nid = "ompal"\n[[signoff]]\nid = "ompal"\n{by_line}date = "2026-09-28"\n',
    )
    v = provenance.check(REGISTER, [p])
    assert any("[[signoff]] for 'ompal' needs a non-empty string `by`" in x for x in v)
    # an anonymous signoff does not clear the verify source either
    assert any("source 'ompal' is verify and has no matching [[signoff]]" in x for x in v)


def test_signoff_without_id_and_by_reports_both(tmp_path):
    p = write_body(tmp_path, "p.toml", "[[signoff]]\ndate = \"2026-09-28\"\n")
    v = provenance.check(REGISTER, [p])
    assert any("without a string `id`" in x for x in v)
    assert any("non-empty string `by`" in x for x in v)


# --- pack coverage: --packs-root ------------------------------------------------------------


def make_pack(root: Path, name: str, body: str = HEADER, artifact_file: str | None = "x.calib.json") -> Path:
    """packs/<name>/PROVENANCE.toml (+ its artifact under the repo root `root`)."""
    d = root / "packs" / name
    d.mkdir(parents=True)
    if body is not None:
        (d / "PROVENANCE.toml").write_text(body, encoding="utf-8")
    if artifact_file is not None:
        (d / artifact_file).write_text("{}", encoding="utf-8")
    return d


def prov(name: str, artifact_file: str = "x.calib.json", extra: str = "") -> str:
    return f'artifact = "packs/{name}/{artifact_file}"\nnote = "test"\n{extra}'


def test_packs_root_passes_when_every_pack_is_covered(tmp_path):
    make_pack(tmp_path, "aaa", prov("aaa"))
    make_pack(tmp_path, "bbb", prov("bbb", extra='[[source]]\nid = "aishell-3"\n'))
    assert provenance.check_packs(REGISTER, tmp_path / "packs") == []


def test_packs_root_flags_subdir_without_provenance_file(tmp_path):
    make_pack(tmp_path, "good", prov("good"))
    make_pack(tmp_path, "foo", body=None, artifact_file="foo.calib.json")
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert len(v) == 1
    assert v[0].endswith("foo: pack has no PROVENANCE.toml")


def test_packs_root_flags_empty_provenance_file(tmp_path):
    make_pack(tmp_path, "foo", body="")
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert len(v) == 2  # artifact and note missing


def test_packs_root_flags_artifact_pointing_at_a_missing_file(tmp_path):
    make_pack(tmp_path, "foo", prov("foo", "gone.calib.json"), artifact_file="present.calib.json")
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert len(v) == 1
    assert "packs/foo/gone.calib.json" in v[0] and "does not exist" in v[0]


def test_artifact_is_resolved_against_the_parent_of_packs_root(tmp_path):
    # artifact paths are repo-root-relative, so the same manifest passes from any cwd
    make_pack(tmp_path, "foo", prov("foo", "foo.calib.json"), artifact_file="foo.calib.json")
    assert provenance.check_packs(REGISTER, tmp_path / "packs") == []
    # a file next to the manifest but not at the repo-root-relative path does not count
    make_pack(tmp_path, "bar", 'artifact = "bar.calib.json"\nnote = "t"\n', artifact_file="bar.calib.json")
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert len(v) == 1 and "bar.calib.json" in v[0]


def test_packs_root_checks_the_sources_of_every_found_file(tmp_path):
    make_pack(tmp_path, "bad", prov("bad", extra='[[source]]\nid = "magicdata-read"\n'))
    make_pack(tmp_path, "ok", prov("ok"))
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert len(v) == 1 and "source 'magicdata-read' is deny" in v[0]


def test_packs_root_ignores_plain_files(tmp_path):
    make_pack(tmp_path, "ok", prov("ok"))
    (tmp_path / "packs" / "README.md").write_text("notes")
    assert provenance.check_packs(REGISTER, tmp_path / "packs") == []


def test_packs_root_that_is_missing_or_not_a_directory_is_a_violation(tmp_path):
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert len(v) == 1 and "packs" in v[0]
    f = write(tmp_path, "packs_file", "x")
    assert len(provenance.check_packs(REGISTER, f)) == 1


def test_packs_root_without_any_pack_is_a_violation(tmp_path):
    (tmp_path / "packs").mkdir()
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert len(v) == 1 and "no pack directories" in v[0]


def test_packs_root_plus_explicit_files(tmp_path):
    make_pack(tmp_path, "ok", prov("ok"))
    assert provenance.check_packs(REGISTER, tmp_path / "packs", [ZERO]) == []
    v = provenance.check_packs(REGISTER, tmp_path / "packs", [MAGICDATA])
    assert len(v) == 1 and "magicdata-read" in v[0]


def test_packs_root_file_also_listed_explicitly_is_checked_once(tmp_path):
    make_pack(tmp_path, "bad", prov("bad", extra='[[source]]\nid = "magicdata-read"\n'))
    pf = tmp_path / "packs" / "bad" / "PROVENANCE.toml"
    assert len(provenance.check_packs(REGISTER, tmp_path / "packs", [pf])) == 1


# --- the real register and real packs -----------------------------------------------------


def test_real_register_is_well_formed():
    with REAL_REGISTER.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)) and ids
    assert {r["shipped_weights_training"] for r in rows} <= {"allow", "verify", "deny", "n/a"}


def test_real_register_verdicts():
    assert provenance.check(REAL_REGISTER, [ZERO, AISHELL3]) == []
    v = provenance.check(REAL_REGISTER, [MAGICDATA])
    assert len(v) == 1 and "source 'magicdata-read' is deny" in v[0]


def test_shipped_pack_provenance_files_pass():
    files = sorted((REPO / "packs").glob("*/PROVENANCE.toml"))
    assert REPO / "packs" / "cmn" / "PROVENANCE.toml" in files  # not vacuous
    assert provenance.check(REAL_REGISTER, files) == []


def test_real_packs_root_passes():
    assert provenance.check_packs(REAL_REGISTER, REPO / "packs") == []


# --- tkh provenance -----------------------------------------------------------------------


def test_cli_exit_0_and_message_when_clean(capsys):
    rc = cli.main(["provenance", "--register", str(REGISTER), str(ZERO), str(AISHELL3), str(OMPAL_SIGNED)])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "provenance ok"


def test_cli_exit_1_and_prints_violations(capsys):
    rc = cli.main(["provenance", "--register", str(REGISTER), str(MAGICDATA), str(OMPAL_UNSIGNED)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "magicdata-read" in out and "ompal" in out
    assert "provenance ok" not in out


def test_cli_missing_register_exits_2(tmp_path, capsys):
    rc = cli.main(["provenance", "--register", str(tmp_path / "nope.csv"), str(ZERO)])
    assert rc == 2
    assert "nope.csv" in capsys.readouterr().err


def test_cli_requires_register_and_something_to_check(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["provenance", str(ZERO)])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        cli.main(["provenance", "--register", str(REGISTER)])
    assert e.value.code == 2
    capsys.readouterr()


def test_cli_packs_root_on_the_real_packs_exits_0(capsys):
    rc = cli.main(["provenance", "--register", str(REAL_REGISTER), "--packs-root", str(REPO / "packs")])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "provenance ok"


def test_cli_packs_root_exits_1_on_uncovered_pack(tmp_path, capsys):
    make_pack(tmp_path, "ok", prov("ok"))
    make_pack(tmp_path, "foo", body=None, artifact_file="foo.calib.json")
    rc = cli.main(["provenance", "--register", str(REGISTER), "--packs-root", str(tmp_path / "packs")])
    assert rc == 1
    out = capsys.readouterr().out
    assert "foo: pack has no PROVENANCE.toml" in out
    assert "provenance ok" not in out


def test_cli_packs_root_with_explicit_files(tmp_path, capsys):
    make_pack(tmp_path, "ok", prov("ok"))
    args = ["provenance", "--register", str(REGISTER), "--packs-root", str(tmp_path / "packs")]
    assert cli.main([*args, str(ZERO)]) == 0
    assert cli.main([*args, str(MAGICDATA)]) == 1
    capsys.readouterr()
