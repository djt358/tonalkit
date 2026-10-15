"""`tkh review`: the page's data and structure, its order (the scorer's doubts first), that it
links only files under the data root by relative paths, and that it loads nothing from the
network. A small synthetic volunteer corpus and a hand-made results file."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote

import pytest
from intake_support import tkh
from relabel_support import CODE, CORPUS, decision, make_corpus, manifest_file, relabel, results_file

from tonekit_harness.review.cards import ReviewError
from tonekit_harness.review.page import _data_block, write_page
from tonekit_harness.review.view import ReviewOptions, page_data
from tonekit_harness.repo import repo_root

C = {card: f"{CODE}-{card}" for card in ("g01-c", "g01-e", "g02-c", "g02-e", "t01-c", "t01-e", "r01", "m01-a")}
HEARD = {
    C["g01-e"]: ["4", "1", "3"],  # the error card heard as the correct word: the twin's reading
    C["g02-c"]: ["4", "2", "1"],  # a correct card heard with another tone
    C["t01-c"]: ["4", None],  # the scorer unsure of a syllable
    C["g01-c"]: ["4", "1", "3"],
    C["g02-e"]: ["4", "3", "4"],
    C["t01-e"]: ["4", "2"],
    C["m01-a"]: ["3"],
}  # r01 is not graded


@pytest.fixture
def root(tmp_path):
    root = make_corpus(tmp_path)
    results_file(root, HEARD)
    return root


def opts(root: Path, **kw) -> ReviewOptions:
    return ReviewOptions(root=root, corpus_id=CORPUS, repo=repo_root(), **kw)


def page_text(root: Path) -> str:
    return (root / "review" / CORPUS / "index.html").read_text(encoding="utf-8")


def embedded(html: str) -> dict:
    return json.loads(re.search(r'<script type="application/json" id="review-data">(.*?)</script>', html, re.S)[1])


def written(root: Path, **kw) -> tuple[str, dict]:
    write_page(root, CORPUS, page_data(opts(root, **kw)))
    html = page_text(root)
    return html, embedded(html)


# ---- what the page shows --------------------------------------------------------------------


def test_the_page_is_written_under_the_data_root_with_one_entry_per_clip(root):
    html, data = written(root)
    assert (root / "review" / CORPUS / "index.html").is_file()
    assert data["corpus"] == CORPUS and data["sessions"] == [CODE] and data["tones"] == ["1", "2", "3", "4", "5"]
    assert sorted(c["id"] for c in data["clips"]) == sorted(C.values())
    assert data["results"] == {"file": f"reports/{CORPUS}.results.json", "register_from": "drill"}
    assert f"<title>Listen and relabel: {CORPUS}</title>" in html


def test_each_clip_shows_its_card_in_both_scripts_its_label_and_the_scorers_view(root):
    _, data = written(root)
    clip = next(c for c in data["clips"] if c["id"] == C["g01-e"])
    assert (clip["text"], clip["traditional"], clip["pinyin"]) == ("一杯睡", "一杯睡", "yì bēi shuì")
    assert (clip["label"], clip["tones"], clip["intended"]) == ("tone_error", ["4", "1", "4"], ["4", "1", "3"])
    assert clip["twin"] == "一杯水" and clip["note"].startswith("Read it as written")
    assert clip["speaker"] == "v-k7q2md" and clip["session"] == CODE and clip["set"] == "gate"
    third = clip["syllables"][2]
    assert (third["label"], third["hanzi"], third["heard"], third["p"]) == ("shui", "睡", "3", 0.9)
    assert third["forms"] == {"1": "shuī", "2": "shuí", "3": "shuǐ", "4": "shuì", "5": "shui"}
    assert clip["now"] is None and clip["applied"] is None


def test_clips_the_scorer_doubts_come_first(root):
    _, data = written(root)
    order = [(c["id"].removeprefix(f"{CODE}-"), c["group"]) for c in data["clips"]]
    assert order == [
        ("g01-e", "twin"),  # heard as the correct word: the twin card's reading
        ("g02-c", "disagrees"),
        ("t01-c", "unsure"),
        ("r01", "not_graded"),
        ("g01-c", "agrees"), ("g02-e", "agrees"), ("t01-e", "agrees"), ("m01-a", "agrees"),
    ]  # fmt: skip


def test_without_results_the_page_has_no_scorer_view_and_keeps_corpus_order(root):
    (root / "reports" / f"{CORPUS}.results.json").unlink()
    _, data = written(root)
    assert data["results"] is None
    assert [c["id"] for c in data["clips"]] == [r for r in (json.loads(x)["id"] for x in manifest_file(root).read_text().splitlines())]
    assert {c["group"] for c in data["clips"]} == {"not_graded"}


def test_speaker_and_set_filters_pick_the_clips(root):
    _, data = written(root, speakers=(CODE.lower(),), sets=("diag_t23",))
    assert sorted(c["id"] for c in data["clips"]) == [C["t01-c"], C["t01-e"]]
    _, data = written(root, speakers=("v-k7q2md",))
    assert len(data["clips"]) == 8 and data["filters"]["speakers"] == ["v-k7q2md"]
    with pytest.raises(ReviewError, match="no clips"):
        page_data(opts(root, speakers=("ABCDEF",)))


def test_after_a_relabel_the_page_still_asks_from_the_card_and_shows_what_was_applied(root):
    relabel(root, decision(C["g01-e"], "heard", ["4", "1", "3"]), decision(C["r01"], "exclude"))
    _, data = written(root)
    by_id = {c["id"]: c for c in data["clips"]}
    g = by_id[C["g01-e"]]
    assert g["tones"] == ["4", "1", "4"] and g["label"] == "tone_error"  # the card's, preselected
    assert g["now"] == {"excluded": False, "label": "correct", "tones": ["4", "1", "3"], "left_pair": True,
                        "needs_listen": False}  # fmt: skip
    assert g["applied"]["verdict"] == "heard" and g["applied"]["tones"] == ["4", "1", "3"]
    r = by_id[C["r01"]]  # excluded from the manifest, still on the page with its audio
    assert r["now"] == {"excluded": True} and r["audio"] is not None


# ---- only relative links, only under the data root ---------------------------------------------


def test_the_page_links_audio_by_relative_paths_that_stay_under_the_data_root(root, tmp_path):
    html, data = written(root)
    page_dir = root / "review" / CORPUS
    for c in data["clips"]:
        assert not c["audio"].startswith("/") and ":" not in c["audio"]
        target = (page_dir / unquote(c["audio"])).resolve()
        assert target.is_file() and target.is_relative_to(root.resolve())
        assert target.read_bytes()[:4] == b"RIFF"
    for absolute in (str(root), str(tmp_path), str(Path.home()), str(repo_root())):
        assert absolute not in html


def test_a_clip_whose_audio_is_outside_the_data_root_gets_no_link(root, tmp_path):
    outside = tmp_path / "elsewhere.wav"
    outside.write_bytes(b"RIFF")
    text = manifest_file(root).read_text()
    rel = Path("../../..") / "elsewhere.wav"  # from corpora/<id>/ out of the data root
    manifest_file(root).write_text(text.replace(f'"audio/{CODE}/r01.wav"', f'"{rel.as_posix()}"'))
    _, data = written(root)
    assert next(c for c in data["clips"] if c["id"] == C["r01"])["audio"] is None


# ---- nothing from the network ---------------------------------------------------------------------


def _csp(html: str) -> str:
    return re.search(r'http-equiv="Content-Security-Policy" content="([^"]*)"', html)[1].replace("&#x27;", "'")


def _hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def test_the_page_loads_nothing_from_the_network(root):
    html, _ = written(root)
    csp = _csp(html)
    assert "default-src 'none'" in csp and "connect-src 'none'" in csp and "form-action 'none'" in csp
    assert "http" not in csp and "*" not in csp and "data:" not in csp
    script = re.findall(r"<script>(.*?)</script>", html, re.S)
    style = re.findall(r"<style>(.*?)</style>", html, re.S)
    assert len(script) == 1 and len(style) == 1
    assert f"script-src {_hash(script[0])}" in csp and f"style-src {_hash(style[0])}" in csp
    assert not re.search(r"<(link|img|iframe|object|embed|base|form)\b", html)
    assert not re.search(r"<script[^>]*\bsrc=", html)
    for needle in ("http://", "https://", "fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "sendBeacon", "import("):
        assert needle not in html


def test_the_data_cannot_end_its_script_block():
    block = _data_block({"note": "</script><script>alert(1)</script> & <!--"})
    assert "<" not in block and ">" not in block and "&" not in block
    assert json.loads(block) == {"note": "</script><script>alert(1)</script> & <!--"}


# ---- tkh review --------------------------------------------------------------------------------------


def test_tkh_review_says_where_the_page_is_and_what_to_run_after(root, capsys):
    code, out, err = tkh(capsys, "review", "--corpus", CORPUS, "--data", str(root))
    assert code == 0, err
    page = root / "review" / CORPUS / "index.html"
    assert f"page: {page}" in out and page.as_uri() in out
    assert "first the 1 where the scorer hears the twin card's reading, then the 1" in out
    assert f"tkh relabel ~/Downloads/relabels-{CORPUS}.json --corpus {CORPUS}" in out


def test_tkh_review_of_a_corpus_that_is_not_there_exits_1(tmp_path, capsys):
    code, _, err = tkh(capsys, "review", "--corpus", "nope", "--data", str(tmp_path))
    assert code == 1 and "no corpus 'nope'" in err
    assert not (tmp_path / "review").exists()
