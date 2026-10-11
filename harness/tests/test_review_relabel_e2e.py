"""End to end on synthetic speech: intake, `tkh eval --results`, `tkh review`, `tkh relabel` of an
export, and `tkh eval` again on the relabelled corpus, whose broken pair leaves the gate's pairs."""

from __future__ import annotations

import shlex

from intake_support import kit_bundle, tkh
from relabel_support import CARDS, CODE, CORPUS, decision, export_file, rows

OTHER = "ABCDEF"


def test_listen_relabel_and_grade_again(tmp_path, capsys):
    data = tmp_path / "data"
    bundles = [kit_bundle(tmp_path / "in", code, CARDS, voiced=True) for code in (CODE, OTHER)]
    code, out, err = tkh(capsys, "intake", *map(str, bundles), "--data", str(data))
    assert code == 0, err
    grade = shlex.split(out.strip().splitlines()[-1])[4:] + ["--no-cache"]
    code, out, err = tkh(capsys, "eval", *grade)
    assert code == 0, err

    code, out, err = tkh(capsys, "review", "--corpus", CORPUS, "--data", str(data))
    assert code == 0, err
    page = (data / "review" / CORPUS / "index.html").read_text(encoding="utf-8")
    assert f"{CODE}-g01-e" in page and "not_graded" not in page.split('id="review-data">')[1].split("</script>")[0]

    path = export_file(tmp_path, decision(f"{CODE}-g01-e", "heard", ["4", "1", "3"]), decision(f"{OTHER}-r01", "exclude"))
    code, out, err = tkh(capsys, "relabel", str(path), "--corpus", CORPUS, "--data", str(data))
    assert code == 0, err
    assert rows(data)[f"{CODE}-g01-e"].label == "correct" and f"{OTHER}-r01" not in rows(data)

    code, out, err = tkh(capsys, "eval", *grade)
    assert code == 0, err
    report = (data / "reports" / f"{CORPUS}.md").read_text(encoding="utf-8")
    assert "## Gate clips outside the pairs" in report
    assert f"- {CODE}-g01-c" in report and f"- {CODE}-g01-e" in report
    assert "3 gate pairs" in report  # four pairs, one left out
