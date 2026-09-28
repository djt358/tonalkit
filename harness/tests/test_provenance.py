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


def write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


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
    p = write(
        tmp_path,
        "p.toml",
        '[[source]]\nid = "ompal"\n[[signoff]]\nid = "mfa-mandarin"\nby = "DJ"\ndate = "2026-09-28"\n',
    )
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "ompal" in v[0]


def test_signoff_never_overrides_deny(tmp_path):
    p = write(
        tmp_path,
        "p.toml",
        '[[source]]\nid = "magicdata-read"\n[[signoff]]\nid = "magicdata-read"\nby = "DJ"\ndate = "2026-09-28"\n',
    )
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "source 'magicdata-read' is deny" in v[0]


def test_unknown_source_id_is_flagged(tmp_path):
    p = write(tmp_path, "p.toml", '[[source]]\nid = "made-up"\n')
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "source 'made-up' is unknown" in v[0]


def test_na_source_is_flagged(tmp_path):
    p = write(tmp_path, "p.toml", '[[source]]\nid = "pyin"\n')
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "source 'pyin' is n/a" in v[0]


def test_unrecognised_register_value_is_flagged(tmp_path):
    reg = write(
        tmp_path,
        "reg.csv",
        "id,shipped_weights_training\nweird,maybe\nblank,\n",
    )
    p = write(tmp_path, "p.toml", '[[source]]\nid = "weird"\n[[source]]\nid = "blank"\n')
    v = provenance.check(reg, [p])
    assert len(v) == 2
    assert "source 'weird' has unrecognised" in v[0] and "'maybe'" in v[0]
    assert "source 'blank' has unrecognised" in v[1]


def test_every_violation_is_reported_across_manifests():
    v = provenance.check(REGISTER, [MAGICDATA, ZERO, OMPAL_UNSIGNED, AISHELL3])
    assert len(v) == 2
    assert "magicdata-read" in v[0] and "ompal" in v[1]


def test_multiple_violations_in_one_manifest(tmp_path):
    p = write(
        tmp_path,
        "p.toml",
        '[[source]]\nid = "magicdata-read"\n[[source]]\nid = "ompal"\n[[source]]\nid = "aishell-3"\n',
    )
    assert len(provenance.check(REGISTER, [p])) == 2


def test_missing_manifest_is_a_violation(tmp_path):
    v = provenance.check(REGISTER, [tmp_path / "packs" / "*" / "PROVENANCE.toml"])
    assert len(v) == 1 and "PROVENANCE.toml" in v[0]


def test_malformed_toml_is_a_violation(tmp_path):
    p = write(tmp_path, "p.toml", "[[source]\nid = ")
    v = provenance.check(REGISTER, [p])
    assert len(v) == 1 and "p.toml" in v[0]


@pytest.mark.parametrize(
    "text",
    [
        '[source]\nid = "aishell-3"\n',  # single table instead of [[source]]
        "source = [1, 2]\n",
        "[[source]]\nuse = \"no id\"\n",
        "[[source]]\nid = 7\n",
        'signoff = "DJ"\n',
        "[[signoff]]\nby = \"DJ\"\n",  # signoff without id
    ],
)
def test_structurally_invalid_manifest_is_a_violation(tmp_path, text):
    v = provenance.check(REGISTER, [write(tmp_path, "p.toml", text)])
    assert len(v) >= 1


def test_register_without_required_columns_raises(tmp_path):
    reg = write(tmp_path, "reg.csv", "id,license\naishell-3,Apache-2.0\n")
    with pytest.raises(provenance.ProvenanceError):
        provenance.check(reg, [ZERO])


def test_duplicate_register_ids_raise(tmp_path):
    reg = write(tmp_path, "reg.csv", "id,shipped_weights_training\na,allow\na,deny\n")
    with pytest.raises(provenance.ProvenanceError):
        provenance.check(reg, [ZERO])


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
    # packs/cmn/PROVENANCE.toml (no sources) lands with the pack crate; every pack that exists
    # must pass.
    files = sorted((REPO / "packs").glob("*/PROVENANCE.toml"))
    assert provenance.check(REAL_REGISTER, files) == []


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


def test_cli_requires_register_and_at_least_one_file(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["provenance", str(ZERO)])
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        cli.main(["provenance", "--register", str(REGISTER)])
    assert e.value.code == 2
    capsys.readouterr()
