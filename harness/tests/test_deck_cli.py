"""tkh deck build and tkh deck check."""

import json
import shutil

from deck_support import DECK_DIR, SOURCES, needs_c0_fix, small_deck_data

from tonekit_harness import cli
from tonekit_harness.deck_build.emit import toml_text


def run(capsys, *argv) -> tuple[int, str, str]:
    code = cli.main(["deck", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def write_deck(tmp_path, data, name="d.toml"):
    path = tmp_path / name
    path.write_text(toml_text(data), encoding="utf-8")
    return path


def test_check_reports_a_good_deck(tmp_path, capsys):
    code, out, err = run(capsys, "check", str(write_deck(tmp_path, small_deck_data())))
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0].startswith("OK ") and "5 cards, 2 pairs" in lines[1]
    assert "sets: register 1, gate 4" in out and "status: unverified 5" in out and "sha256 " in out


def test_check_refuses_an_error_card_that_changes_two_surface_tones_and_says_so(tmp_path, capsys):
    data = small_deck_data()
    error = next(c for c in data["card"] if c["id"] == "g01-e")
    # 一杯水 is yì bēi shuǐ; here the error is also read with a changed first syllable (yí): two tones differ
    error["pinyin"], error["citation_pinyin"] = "yí bēi shuì", "yī bēi shuì"
    error["produced_tones"] = ["2", "1", "4"]
    code, out, err = run(capsys, "check", str(write_deck(tmp_path, data)))
    assert code == 1 and out == ""
    assert err.startswith("FAIL ")
    assert "card 'g01-e'" in err and "differ from intended in 2 positions" in err and "it needs exactly one" in err
    assert err.rstrip().endswith("problems") or "problem" in err.splitlines()[-1]


def test_check_refuses_citation_tones_where_speakers_produce_sandhi(tmp_path, capsys):
    data = small_deck_data()
    correct = next(c for c in data["card"] if c["id"] == "g01-c")
    # the dictionary form, "solitaire", where speakers say yì bēi shuǐ
    correct["pinyin"], correct["produced_tones"], correct["intended"]["tones"] = (
        "yī bēi shuǐ",
        ["1", "1", "3"],
        ["1", "1", "3"],
    )
    code, _, err = run(capsys, "check", str(write_deck(tmp_path, data)))
    assert code == 1
    assert "phrase reading 1-1-3 is not a sandhi reading of 'yī bēi shuǐ' (4-1-3)" in err


def test_check_lists_every_problem_and_counts_them(tmp_path, capsys):
    data = small_deck_data()
    data["card"][1]["pinyin"] = "yī bēi shuǐ"
    data["card"][3]["pinyin"] = "yī běn shū"
    code, _, err = run(capsys, "check", str(write_deck(tmp_path, data)))
    assert code == 1 and err.count("is not a sandhi reading") + err.count("but produced_tones") >= 2
    assert err.splitlines()[-1].endswith(" problems")


def test_check_says_when_the_file_is_missing_or_not_toml(tmp_path, capsys):
    code, _, err = run(capsys, "check", str(tmp_path / "nope.toml"))
    assert code == 1 and err.startswith("error: cannot read")
    bad = tmp_path / "bad.toml"
    bad.write_text("[deck\n", encoding="utf-8")
    code, _, err = run(capsys, "check", str(bad))
    assert code == 1 and "invalid TOML" in err


@needs_c0_fix
def test_check_reads_the_kits_json_too(tmp_path, capsys):
    path = tmp_path / "d.json"
    path.write_text(json.dumps(small_deck_data(), ensure_ascii=False), encoding="utf-8")
    code, out, _ = run(capsys, "check", str(path))
    assert code == 0 and "5 cards" in out


def copy_sources(tmp_path):
    out = tmp_path / "sources"
    shutil.copytree(SOURCES, out)
    return out


@needs_c0_fix
def test_build_writes_the_contract_file_and_the_json_and_the_audit_sheet(tmp_path, capsys):
    out = tmp_path / "out"
    code, text, err = run(capsys, "build", "--out", str(out), "--audit", str(tmp_path / "audit.md"))
    assert code == 0 and err == ""
    assert (out / "s05-v1.toml").exists() and (out / "s05-v1.json").exists()
    assert "76 cards" in text and "gate: 20 pairs chosen" in text
    audit = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert audit.startswith("Gate phrases: the stand-in gate_standin.csv.") and "| id | set | text |" in audit
    code, text, _ = run(capsys, "check", str(out / "s05-v1.toml"))
    assert code == 0 and "76 cards" in text


@needs_c0_fix
def test_build_takes_the_gate_phrases_from_a_gmeasure_table(tmp_path, capsys):
    table = tmp_path / "g_measure.csv"
    table.write_text(
        "word,measure,citation_pinyin,spoken_pinyin\n水,杯,yī bēi shuǐ,yì bēi shuǐ\n书,本,yī běn shū,yì běn shū\n"
        "车,辆,yī liàng chē,yí liàng chē\n纸,张,yī zhāng zhǐ,yī zhāng zhǐ\n咖啡,杯,yī bēi kā fēi,yì bēi kā fēi\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    code, text, _ = run(capsys, "build", "--out", str(out), "--gmeasure", str(table), "--gate-pairs", "3")
    assert code == 0
    assert "gate: 3 pairs chosen" in text
    assert "can't use g_measure.csv:5 一张纸: its own pinyin does not hold" in text
    assert "can't use g_measure.csv:6 一杯咖啡" in text
    deck = json.loads((out / "s05-v1.json").read_text(encoding="utf-8"))
    gate = [c["text"] for c in deck["card"] if c["set"] == "gate" and c["label"] == "correct"]
    assert gate == ["一杯水", "一本书", "一辆车"]


def test_build_reports_a_broken_source_and_writes_nothing(tmp_path, capsys):
    sources = copy_sources(tmp_path)
    (sources / "register.csv").write_text("text,citation_pinyin\n妈,mā\n", encoding="utf-8")
    out = tmp_path / "out"
    code, text, err = run(capsys, "build", "--sources", str(sources), "--out", str(out))
    assert code == 1 and text == "" and "register.csv: missing column(s) spoken_pinyin" in err
    assert not out.exists()


def test_build_with_a_bad_gmeasure_map_or_table(tmp_path, capsys):
    code, _, err = run(capsys, "build", "--out", str(tmp_path), "--gmeasure-map", "text")
    assert code == 1 and "wants FIELD=COLUMN" in err
    code, _, err = run(capsys, "build", "--out", str(tmp_path), "--gmeasure", str(tmp_path / "none.csv"))
    assert code == 1 and "cannot read" in err


def test_the_deck_dir_default_is_the_kit_deck_directory():
    assert DECK_DIR.name == "deck" and DECK_DIR.parent.name == "kit"
