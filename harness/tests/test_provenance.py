import csv
import tomllib
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


# --- unreadable input: a clean error that names the file, never a traceback ---------------


def test_a_register_that_is_not_utf8_raises_a_provenance_error_naming_it(tmp_path):
    reg = tmp_path / "reg.csv"
    reg.write_bytes(b"id,shipped_weights_training\nname\xff,allow\n")
    with pytest.raises(provenance.ProvenanceError, match="reg.csv"):
        provenance.check(reg, [ZERO])


def test_a_malformed_register_csv_raises_a_provenance_error_naming_it(tmp_path):
    # A field longer than csv's 128 KiB limit is a csv.Error (relies on the default
    # csv.field_size_limit of 131072).
    reg = write(tmp_path, "reg.csv", "id,shipped_weights_training\na," + "x" * 200_000 + "\n")
    with pytest.raises(provenance.ProvenanceError, match="reg.csv"):
        provenance.check(reg, [ZERO])


def test_a_manifest_that_is_not_utf8_is_a_violation_naming_it(tmp_path):
    p = tmp_path / "PROVENANCE.toml"
    p.write_bytes(b'artifact = "\xff"\nnote = "t"\n')
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "PROVENANCE.toml" in v[0] and "cannot read manifest" in v[0]


def test_packs_root_survives_a_manifest_that_is_not_utf8(tmp_path):
    d = make_pack(tmp_path, "foo", body=None)
    (d / "PROVENANCE.toml").write_bytes(b"\xff\xfe")
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert len(v) == 1 and "foo" in v[0] and "cannot read manifest" in v[0]


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
    make_pack(tmp_path, "foo", prov("foo", "gone.calib.json"), artifact_file=None)
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert len(v) == 1
    assert "packs/foo/gone.calib.json" in v[0] and "does not exist" in v[0]


def one_bad_pack(tmp_path, artifact_toml: str, *, files: dict[str, str | None] | None = None):
    """A valid pack `bar`, plus pack `foo` whose manifest says `artifact = <artifact_toml>` (TOML
    text), plus `files` under the repo root (a value of None makes a directory). Returns the
    violations of `check_packs`."""
    make_pack(tmp_path, "bar", prov("bar"))
    make_pack(tmp_path, "foo", f"artifact = {artifact_toml}\nnote = \"t\"\n", artifact_file=None)
    for name, text in (files or {}).items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            path.mkdir()
        else:
            path.write_text(text, encoding="utf-8")
    return provenance.check_packs(REGISTER, tmp_path / "packs")


def test_an_absolute_artifact_path_is_a_violation_even_if_the_file_exists(tmp_path):
    existing = tmp_path / "packs" / "foo" / "x.calib.json"
    v = one_bad_pack(tmp_path, f'"{existing.as_posix()}"', files={"packs/foo/x.calib.json": "{}"})
    assert existing.is_file()
    assert len(v) == 1 and "relative" in v[0] and "foo" in v[0]


@pytest.mark.parametrize(
    "artifact",
    [
        "packs/foo/../../secret.json",  # out of the repo root
        "packs/foo/../bar/x.calib.json",  # into another pack
        "packs/bar/x.calib.json",  # another pack's file, no `..`
        "secret.json",  # inside the repo root but outside the pack
    ],
)
def test_an_artifact_outside_the_pack_directory_is_a_violation(tmp_path, artifact):
    (tmp_path / "secret.json").write_text("{}", encoding="utf-8")
    v = one_bad_pack(tmp_path, f'"{artifact}"')
    assert len(v) == 1 and "outside the pack directory" in v[0] and "foo" in v[0]


def test_an_artifact_that_is_a_directory_is_a_violation(tmp_path):
    v = one_bad_pack(tmp_path, '"packs/foo/sub"', files={"packs/foo/sub": None})
    assert len(v) == 1 and "not a regular file" in v[0]


def test_a_symlink_out_of_the_pack_directory_is_a_violation(tmp_path):
    (tmp_path / "secret.json").write_text("{}", encoding="utf-8")
    make_pack(tmp_path, "foo", prov("foo", "link.json"), artifact_file=None)
    try:
        (tmp_path / "packs" / "foo" / "link.json").symlink_to(tmp_path / "secret.json")
    except OSError:
        pytest.skip("cannot create symlinks here")
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert len(v) == 1 and "outside the pack directory" in v[0]


def test_an_artifact_path_the_filesystem_cannot_take_is_a_violation(tmp_path):
    v = one_bad_pack(tmp_path, '"packs/foo/x\\u0000.json"')  # an embedded NUL character
    assert len(v) == 1 and "foo" in v[0] and "not a usable path" in v[0]


def test_a_self_referential_symlink_artifact_is_a_violation_not_a_traceback(tmp_path):
    # `loop.json -> loop.json`: Path.resolve() raises RuntimeError on Python 3.11/3.12 (later
    # versions return the path and `exists()` is False), so it is a violation either way.
    make_pack(tmp_path, "foo", prov("foo", "loop.json"), artifact_file=None)
    try:
        (tmp_path / "packs" / "foo" / "loop.json").symlink_to("loop.json")
    except OSError:
        pytest.skip("cannot create symlinks here")
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert len(v) == 1 and "loop.json" in v[0]
    assert "not a usable path" in v[0] or "does not exist" in v[0]


def test_a_regular_file_inside_the_pack_directory_passes(tmp_path):
    v = one_bad_pack(tmp_path, '"packs/foo/sub/deep.json"', files={"packs/foo/sub/deep.json": "{}"})
    assert v == []


def test_artifact_is_resolved_against_the_parent_of_packs_root(tmp_path):
    # artifact paths are repo-root-relative, so the same manifest passes from any cwd
    make_pack(tmp_path, "foo", prov("foo", "foo.calib.json"), artifact_file="foo.calib.json")
    assert provenance.check_packs(REGISTER, tmp_path / "packs") == []
    # a file next to the manifest but not at the repo-root-relative path does not count
    make_pack(tmp_path, "bar", 'artifact = "bar.calib.json"\nnote = "t"\n', artifact_file="bar.calib.json")
    v = provenance.check_packs(REGISTER, tmp_path / "packs")
    assert any("artifact 'bar.calib.json'" in x for x in v)  # not the file next to the manifest
    assert any("packs/bar/bar.calib.json" in x and "not covered" in x for x in v)


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


# --- every data file in a pack is attested: `artifacts` and coverage -------------------------


def prov_many(name: str, files: list[str], extra: str = "") -> str:
    listed = ", ".join(f'"packs/{name}/{f}"' for f in files)
    return f'artifacts = [{listed}]\nnote = "test"\n{extra}'


def _root(pack: Path) -> Path:
    return pack.parent  # the packs root


def pack_with(tmp_path: Path, manifest_body: str, *files: str) -> Path:
    """packs/foo with the given manifest text and (empty JSON or TOML) files of these names."""
    d = make_pack(tmp_path, "foo", manifest_body, artifact_file=None)
    for name in files:
        path = d / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if name.endswith(".json") else "", encoding="utf-8")
    return d


def test_artifacts_lists_every_attested_file(tmp_path):
    pack_with(tmp_path, prov_many("foo", ["foo.toml", "foo.calib.json"]), "foo.toml", "foo.calib.json")
    assert provenance.check_packs(REGISTER, tmp_path / "packs") == []


def test_the_single_artifact_key_still_works(tmp_path):
    pack_with(tmp_path, prov("foo", "foo.calib.json"), "foo.calib.json")
    assert provenance.check_packs(REGISTER, tmp_path / "packs") == []


def test_artifact_and_artifacts_together_are_a_violation(tmp_path):
    body = prov("foo", "a.json") + 'artifacts = ["packs/foo/b.json"]\n'
    v = provenance.check_packs(REGISTER, _root(pack_with(tmp_path, body, "a.json", "b.json")))
    assert len(v) == 1 and "not both" in v[0]


@pytest.mark.parametrize(
    "value",
    ["[]", '"packs/foo/a.json"', '["packs/foo/a.json", ""]', '["packs/foo/a.json", 7]', "7", '[["a"]]'],
)
def test_malformed_artifacts_is_a_violation(tmp_path, value):
    body = f'artifacts = {value}\nnote = "t"\n'
    v = provenance.check_packs(REGISTER, _root(pack_with(tmp_path, body, "a.json")))
    assert len(v) == 1 and "`artifacts` must be a non-empty array of non-empty strings" in v[0]


def test_every_listed_artifact_must_exist_inside_the_pack(tmp_path):
    body = prov_many("foo", ["here.json", "gone.json"])
    v = provenance.check_packs(REGISTER, _root(pack_with(tmp_path, body, "here.json")))
    assert len(v) == 1 and "packs/foo/gone.json" in v[0] and "does not exist" in v[0]


def test_a_json_data_file_the_manifest_does_not_list_is_a_violation(tmp_path):
    body = prov("foo", "foo.calib.json")
    v = provenance.check_packs(
        REGISTER, _root(pack_with(tmp_path, body, "foo.calib.json", "extra.calib.json"))
    )
    assert len(v) == 1
    assert "packs/foo/extra.calib.json" in v[0] and "not covered" in v[0] and "PROVENANCE.toml" in v[0]


def test_a_toml_data_file_the_manifest_does_not_list_is_a_violation(tmp_path):
    # the pack file itself (fitted in P1) is as much data as the calibration
    body = prov("foo", "foo.calib.json")
    v = provenance.check_packs(REGISTER, _root(pack_with(tmp_path, body, "foo.calib.json", "foo.toml")))
    assert len(v) == 1 and "packs/foo/foo.toml" in v[0] and "not covered" in v[0]


def test_every_uncovered_file_is_reported(tmp_path):
    body = prov("foo", "a.json")
    v = provenance.check_packs(REGISTER, _root(pack_with(tmp_path, body, "a.json", "b.json", "c.toml")))
    assert len(v) == 2
    assert "packs/foo/b.json" in v[0] and "packs/foo/c.toml" in v[1]


def test_an_uncovered_data_file_below_a_subdirectory_is_a_violation(tmp_path):
    body = prov("foo", "a.json")
    v = provenance.check_packs(REGISTER, _root(pack_with(tmp_path, body, "a.json", "extra/deep.json")))
    assert len(v) == 1 and "packs/foo/extra/deep.json" in v[0]


def test_the_manifest_itself_and_non_data_files_need_no_coverage(tmp_path):
    body = prov("foo", "a.json")
    d = pack_with(tmp_path, body, "a.json")
    (d / "README.md").write_text("notes", encoding="utf-8")
    (d / "clip.wav").write_bytes(b"RIFF")
    (d / "sub").mkdir()
    assert provenance.check_packs(REGISTER, tmp_path / "packs") == []


def test_extensions_are_matched_without_regard_to_case(tmp_path):
    body = prov("foo", "a.json")
    v = provenance.check_packs(REGISTER, _root(pack_with(tmp_path, body, "a.json", "B.JSON", "C.Toml")))
    assert len(v) == 2 and "B.JSON" in v[0] and "C.Toml" in v[1]


def test_coverage_is_not_asked_of_a_manifest_that_lists_no_artifact(tmp_path):
    # the missing key is the violation; it is not repeated once per data file
    v = provenance.check_packs(REGISTER, _root(pack_with(tmp_path, 'note = "t"\n', "a.json", "b.toml")))
    assert len(v) == 1 and "missing required key `artifact`" in v[0]


def test_cli_packs_root_exits_1_on_an_uncovered_data_file(tmp_path, capsys):
    pack_with(tmp_path, prov("foo", "a.json"), "a.json", "extra.json")
    rc = cli.main(["provenance", "--register", str(REGISTER), "--packs-root", str(tmp_path / "packs")])
    assert rc == 1
    out = capsys.readouterr().out
    assert "extra.json" in out and "not covered" in out and "provenance ok" not in out


def test_the_real_cmn_provenance_attests_the_pack_and_its_calibration():
    doc = tomllib.loads((REPO / "packs" / "cmn" / "PROVENANCE.toml").read_text(encoding="utf-8"))
    assert doc["artifacts"] == ["packs/cmn/cmn.toml", "packs/cmn/cmn.calib.json"]
    assert "artifact" not in doc
    assert "not fitted" in doc["note"]


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


def test_cli_register_that_is_not_utf8_exits_2_naming_it(tmp_path, capsys):
    reg = tmp_path / "reg.csv"
    reg.write_bytes(b"id,shipped_weights_training\nname\xff,allow\n")
    rc = cli.main(["provenance", "--register", str(reg), str(ZERO)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "reg.csv" in err and "Traceback" not in err


def test_cli_empty_packs_root_is_refused_even_when_files_are_given(capsys):
    """`--packs-root ""` (say, an unset shell variable) must not be skipped as if it was absent."""
    with pytest.raises(SystemExit) as e:
        cli.main(["provenance", "--register", str(REGISTER), "--packs-root", "", str(ZERO)])
    assert e.value.code == 2
    assert "--packs-root" in capsys.readouterr().err


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
