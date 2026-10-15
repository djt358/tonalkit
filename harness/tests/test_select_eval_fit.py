"""`tkh eval --select` and `tkh fit --select`: clips composed across the corpora of a data root, each
speaker graded against their own accent, the registry's refusals wired in, and the same answer as
over the equivalent manifest. The data root holds a volunteer corpus written by `tkh intake` (two
kit sessions said by the synthetic test voice) and a public corpus written the way an adapter
writes one (contracts section 3); every clip is synthetic audio (tests/support.py)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from intake_support import kit_bundle, kit_session, options, tkh
from registry_support import CALIB, DEV, HELDOUT, SYNTHETIC_CALIB, add_corpus, speaker
from support import make_clip

from tonekit_harness import evaluate
from tonekit_harness.contracts.registry import load_corpus_file
from tonekit_harness.eval_results import load_results
from tonekit_harness.intake.corpus_toml import corpus_toml_text
from tonekit_harness.intake.run import intake_bundle
from tonekit_harness.registry.runs import selection_from
from tonekit_harness.registry.selectors import parse_selector
from tonekit_harness.session_order import reading_order

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"
VOLUNTEERS = "volunteers-s05-v1"
CARDS = ["r01", "r02", "g01-c", "g01-e", "g02-c", "g02-e"]  # deck order: the manifest's
READ = ["r01", "r02", "g01-e", "g01-c", "g02-e", "g02-c"]  # the order K7Q2MD read them in (session.json)
MAINLAND = {"background": "native", "grew_up_hearing": "mainland", "reading": "hanzi+pinyin", "script": "simplified"}


def gate_clips(directory: Path, spk: str, source: str) -> list:
    """Two gate pairs said by `spk`, written under `<directory>/audio/<spk>/`, paths relative to
    `directory` (where the manifest is)."""
    audio = directory / "audio" / spk
    clips = [
        make_clip(audio, f"{spk}-g01-c", ["4", "1", "3"], pair=f"{spk}-g01", speaker=spk, source=source),
        make_clip(audio, f"{spk}-g01-e", ["4", "2", "3"], intended=["4", "1", "3"], pair=f"{spk}-g01",
                  label="tone_error", speaker=spk, source=source),
        make_clip(audio, f"{spk}-g02-c", ["1", "2", "4"], pair=f"{spk}-g02", speaker=spk, source=source, seed=1),
        make_clip(audio, f"{spk}-g02-e", ["1", "3", "4"], intended=["1", "2", "4"], pair=f"{spk}-g02",
                  label="tone_error", speaker=spk, source=source, seed=1),
    ]  # fmt: skip
    return [c.model_copy(update={"path": f"audio/{spk}/{c.path}"}) for c in clips]


def public_corpus(root: Path, corpus_id: str, *, source: str, kind: str = "public", speakers=None) -> None:
    """A corpus as an adapter writes one: corpus.toml with hash-split speakers, audio under the
    corpus, manifest rows whose source is the corpus's."""
    speakers = speakers or [speaker(CALIB, "calib"), speaker(DEV, "dev"), speaker(HELDOUT, "heldout")]
    directory = root / "corpora" / corpus_id
    clips = [c for s in speakers for c in gate_clips(directory, s["id"], source)]
    add_corpus(root, corpus_id, kind=kind, source=source, speakers=speakers, clips=clips)


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("data")
    inbox = tmp_path_factory.mktemp("in")
    taiwan = kit_bundle(inbox, "K7Q2MD", READ, voiced=True)  # grew up hearing taiwan: cmn-TW
    mainland = kit_bundle(inbox, "ABCDEF", voiced=True, session=kit_session("ABCDEF", CARDS, speaker=MAINLAND))
    for bundle in (taiwan, mainland):
        intake_bundle(bundle, options(root))
    public_corpus(root, "aishell3", source="aishell-3")
    return root


@pytest.fixture
def own(data, tmp_path) -> Path:
    """A copy of the data root a test may change."""
    return Path(shutil.copytree(data, tmp_path / "data", symlinks=True))


def eval_run(capsys, out: Path, *argv: str) -> tuple[int, str, str]:
    """`tkh eval ARGV` with the checkout's pack, a report and results under `out`, and no cache."""
    out.mkdir(parents=True, exist_ok=True)
    return tkh(
        capsys, "eval", *argv, "--pack", str(PACKS / "cmn.toml"),
        "--report", str(out / "report.md"), "--results", str(out / "results.json"), "--no-cache",
    )  # fmt: skip


def fit_run(capsys, out: Path, *argv: str) -> tuple[int, str, str]:
    return tkh(
        capsys, "fit", *argv, "--pack", str(PACKS / "cmn.toml"), "--calib", str(PACKS / "cmn.calib.json"),
        "--out-calib", str(out), "--rounds", "1",
    )  # fmt: skip


def unqualified(results: Path, corpus_id: str) -> list[dict]:
    """The per-clip results with the corpus taken off ids, speakers and pairs."""
    def bare(v):
        return v.removeprefix(f"{corpus_id}/") if isinstance(v, str) else v

    return [
        {k: bare(v) if k in ("id", "speaker", "pair") else v for k, v in c.model_dump().items()}
        for c in load_results(results).clips
    ]


def headline(out: str) -> str:
    return next(line for line in out.splitlines() if line.startswith("S1: ")).split("; report written")[0]


# ---- the same answer as the equivalent manifest -----------------------------------------------------


@pytest.mark.parametrize("register_from", ["drill", "rolling"])
def test_eval_over_a_selection_equals_eval_over_the_manifest(data, tmp_path, capsys, register_from):
    manifest = data / "corpora" / VOLUNTEERS / "manifest.jsonl"
    same = ("--accent", "cmn-standard", "--register-from", register_from)
    code, by_manifest, err = eval_run(capsys, tmp_path / "m", "--manifest", str(manifest), *same)
    assert code == 0, err
    code, by_selection, err = eval_run(capsys, tmp_path / "s", "--select", VOLUNTEERS, "--data", str(data), *same)
    assert code == 0, err
    assert headline(by_selection) == headline(by_manifest)
    assert unqualified(tmp_path / "s" / "results.json", VOLUNTEERS) == unqualified(tmp_path / "m" / "results.json", VOLUNTEERS)
    ids = [c.id for c in load_results(tmp_path / "s" / "results.json").clips]
    assert ids[0] == f"{VOLUNTEERS}/K7Q2MD-r01" and len(ids) == 12


def test_a_selection_reads_each_session_in_the_order_it_was_read(data):
    # what `--register-from rolling` follows: the session.json copy in each corpus directory
    selection = selection_from([parse_selector(VOLUNTEERS)], data, PACKS / "cmn.toml", default_splits=None)
    assert [c.card for c in selection.clips if c.speaker == "v-k7q2md"] == CARDS
    order = reading_order(selection.grading_clips(), selection.audio_root)[f"{VOLUNTEERS}/v-k7q2md"]
    assert [c.card for c in order] == READ


def test_fit_over_a_selection_equals_fit_over_the_manifest(data, tmp_path, capsys):
    manifest = data / "corpora" / "aishell3" / "manifest.jsonl"  # its corpus.toml says SSB0001 is calib
    code, _, err = fit_run(capsys, tmp_path / "m.json", "--manifest", str(manifest))
    assert code == 0, err
    code, out, err = fit_run(capsys, tmp_path / "s.json", "--select", "aishell3", "--data", str(data))
    assert code == 0, err
    assert (tmp_path / "s.json").read_text(encoding="utf-8") == (tmp_path / "m.json").read_text(encoding="utf-8")
    assert f"fitted on 4 clips of aishell3/{CALIB};" in out
    assert 'list them in the pack\'s PROVENANCE.toml as corpora = ["aishell3"] (R113)' in out


# ---- composing corpora ------------------------------------------------------------------------------


def test_fit_composes_a_public_corpus_with_volunteers_moved_to_calib(own, tmp_path, capsys):
    path = own / "corpora" / VOLUNTEERS / "corpus.toml"
    corpus = load_corpus_file(path)
    moved = corpus.model_copy(update={"speaker": [s.model_copy(update={"split": "calib"}) for s in corpus.speaker]})
    path.write_text(corpus_toml_text(moved), encoding="utf-8")  # a recorded corpus may move speakers (R72)
    code, out, err = fit_run(capsys, tmp_path / "c.json", "--data", str(own), "--select", "aishell3:calib",
                             "--select", "volunteers-*:calib")  # fmt: skip
    assert code == 0, err
    assert f"fitted on 16 clips of aishell3/{CALIB}, {VOLUNTEERS}/v-abcdef, {VOLUNTEERS}/v-k7q2md;" in out
    assert f'corpora = ["aishell3", "{VOLUNTEERS}"]' in out


def test_eval_composes_corpora_and_grades_each_speaker_against_their_accent(data, tmp_path, capsys, monkeypatch):
    sent: dict[str, str] = {}  # clip id -> the accent its assessment asked for
    real_assess, real_tonekit = evaluate.Grader.assess, evaluate.tonekit_py.assess
    current = {}

    def assess(self, clip, analysis_json):
        current["id"] = clip.id
        return real_assess(self, clip, analysis_json)

    def tonekit_assess(analysis, pack, calib, request):
        sent[current["id"]] = json.loads(request)["grading"]["accent"]
        return real_tonekit(analysis, pack, calib, request)

    monkeypatch.setattr(evaluate.Grader, "assess", assess)
    monkeypatch.setattr(evaluate.tonekit_py, "assess", tonekit_assess)
    code, out, err = eval_run(capsys, tmp_path / "e", "--data", str(data), "--select", "aishell3:calib",
                              "--select", "volunteers-*")  # fmt: skip
    assert code == 0, err
    speaker_of = {c.id: c.speaker for c in load_results(tmp_path / "e" / "results.json").clips}
    accents: dict[str, set[str]] = {}
    for cid, accent in sent.items():
        accents.setdefault(speaker_of[cid], set()).add(accent)
    assert accents == {
        f"aishell3/{CALIB}": {"cmn-standard"},  # a public speaker: no accent stored, nothing known
        f"{VOLUNTEERS}/v-k7q2md": {"cmn-TW"},  # grew up hearing taiwan
        f"{VOLUNTEERS}/v-abcdef": {"cmn-standard"},  # mainland
    }
    assert len(sent) == 16
    report = (tmp_path / "e" / "report.md").read_text(encoding="utf-8")
    assert "- accent: each speaker's, from the corpus registry (cmn-TW 1 speaker, cmn-standard 2 speakers)" in report
    assert f"- corpora: aishell3 (public, aishell-3): 4 clips of 1 speaker (calib 4); {VOLUNTEERS} (recorded" in report
    # a real, cleared selection may back a verdict
    assert headline(out).startswith(("S1: PASS", "S1: FAIL")) and "not a gate" not in out

    sent.clear()
    code, _, err = eval_run(capsys, tmp_path / "o", "--data", str(data), "--select", "volunteers-*", "--accent", "cmn-standard")
    assert code == 0, err
    assert set(sent.values()) == {"cmn-standard"}  # --accent overrides every speaker's


def test_eval_takes_one_speaker_of_a_selection_by_its_qualified_id(data, tmp_path, capsys):
    code, _, err = eval_run(capsys, tmp_path / "e", "--data", str(data), "--select", "volunteers-*",
                            "--speaker", f"{VOLUNTEERS}/v-abcdef")  # fmt: skip
    assert code == 0, err
    assert {c.speaker for c in load_results(tmp_path / "e" / "results.json").clips} == {f"{VOLUNTEERS}/v-abcdef"}
    code, _, err = eval_run(capsys, tmp_path / "x", "--data", str(data), "--select", "volunteers-*", "--speaker", "v-abcdef")
    assert code == 1 and "speaker(s) v-abcdef not in the selection" in err


# ---- refusals ---------------------------------------------------------------------------------------


def test_eval_says_why_a_selection_is_not_a_gate(own, tmp_path, capsys):
    # A synthetic corpus whose source the register clears and whose clips are not marked synthetic:
    # only the registry's for_gate (corpus kind) catches it.
    public_corpus(own, "tts", source="dj-corpus", kind="synthetic", speakers=[speaker(SYNTHETIC_CALIB, "calib")])
    code, out, err = eval_run(capsys, tmp_path / "e", "--data", str(own), "--select", "aishell3:calib", "--select", "tts")
    assert code == 0, err
    assert headline(out).startswith("S1: NOT A GATE (4 synthetic / non-allowed clips)")
    assert "not a gate verdict, because:\n  tts: synthetic corpus (4 clips); a gate is measured on real recordings" in out
    report = (tmp_path / "e" / "report.md").read_text(encoding="utf-8")
    assert "- not a gate, because: tts: synthetic corpus (4 clips)" in report
    code, out, _ = eval_run(capsys, tmp_path / "s", "--data", str(own), "--select", "tts", "--allow-synthetic")
    assert headline(out).startswith("S1: SMOKE (synthetic)")


def test_eval_on_a_source_the_register_does_not_clear_is_not_a_gate(own, tmp_path, capsys):
    public_corpus(own, "l2", source="latic", speakers=[speaker(CALIB, "calib")])
    code, out, _ = eval_run(capsys, tmp_path / "e", "--data", str(own), "--select", "l2", "--allow-synthetic")
    assert code == 0 and headline(out).startswith("S1: NOT A GATE (4 synthetic / non-allowed clips)")
    assert "l2: source 'latic' is 'verify' in the data register, not 'allow' (4 clips)" in out


@pytest.mark.parametrize(
    "selectors,why",
    [
        (["volunteers-*"], "selects no clips: volunteers-s05-v1 has no clips of a speaker in split calib"),
        ([f"{VOLUNTEERS}:gate"], f"{VOLUNTEERS}/v-k7q2md: speaker is in split 'gate' (6 clips); a fit never sees"),
        (["aishell3:heldout"], f"aishell3/{HELDOUT}: speaker is in split 'heldout' (4 clips)"),
        (["aishell3:calib", "aishell3:dev"], f"speaker(s) aishell3/{DEV} are not in the calib split"),
        (["thchs30"], "select: no corpus 'thchs30' (corpora: aishell3, volunteers-s05-v1)"),
    ],
)
def test_fit_refuses_what_it_may_not_fit_on_and_writes_nothing(data, tmp_path, capsys, selectors, why):
    out = tmp_path / "fitted.calib.json"
    argv = [a for s in selectors for a in ("--select", s)]
    code, _, err = fit_run(capsys, out, "--data", str(data), *argv)
    assert code == 1 and why in err and not out.exists()


def test_fit_refuses_a_source_not_cleared_for_calibration(own, tmp_path, capsys):
    public_corpus(own, "l2", source="latic", speakers=[speaker(CALIB, "calib")])
    code, _, err = fit_run(capsys, tmp_path / "f.json", "--data", str(own), "--select", "l2")
    assert code == 1
    assert "refusing to fit parameters on this selection:\n  l2: source 'latic' is 'verify' in the data register" in err


def test_a_malformed_selector_or_two_clip_sources_is_a_usage_error(data, tmp_path, capsys):
    with pytest.raises(SystemExit) as stop:
        fit_run(capsys, tmp_path / "f.json", "--data", str(data), "--select", "aishell3:train")
    assert stop.value.code == 2
    assert "argument --select: --select 'aishell3:train': unknown split train" in capsys.readouterr().err
    with pytest.raises(SystemExit) as stop:
        eval_run(capsys, tmp_path / "e", "--select", "aishell3", "--manifest", "m.jsonl")
    assert stop.value.code == 2 and "not allowed with argument" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        eval_run(capsys, tmp_path / "e")  # neither
    assert "one of the arguments --manifest --select" in capsys.readouterr().err


def test_fit_with_select_takes_no_corpus_toml_and_an_empty_data_root_is_refused(data, tmp_path, capsys):
    code, _, err = fit_run(capsys, tmp_path / "f.json", "--data", str(data), "--select", "aishell3", "--corpus", "x.toml")
    assert code == 1 and "--corpus names the corpus.toml of a --manifest" in err
    for command in (fit_run, eval_run):
        code, _, err = command(capsys, tmp_path / "f", "--data", "", "--select", "aishell3")
        assert code == 1 and "--data is empty" in err


def test_the_data_root_may_come_before_the_command(data, tmp_path, capsys):
    out = tmp_path / "f.json"
    code, _, err = tkh(capsys, "--data", str(data), "fit", "--select", "aishell3", "--pack", str(PACKS / "cmn.toml"),
                       "--out-calib", str(out), "--rounds", "1")  # fmt: skip
    assert code == 0, err
    assert out.exists()


def test_tkh_corpora_lists_what_intake_and_an_adapter_wrote(data, capsys):
    code, out, err = tkh(capsys, "corpora", "--data", str(data))
    assert code == 0, err
    rows = {line.split()[0]: line.split() for line in out.splitlines()[2:]}
    assert rows["aishell3"][:3] == ["aishell3", "public", "aishell-3"]
    assert rows[VOLUNTEERS][:5] == [VOLUNTEERS, "recorded", "volunteer-corpus", "gate", "2"]
