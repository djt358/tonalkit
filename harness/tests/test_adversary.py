"""The random-search adversary: what counts as a find, the order and files it returns, and that a
failing trial never stops the search. Most tests replace tonekit's grader with a scripted one, so
they check the search's bookkeeping quickly; the θ = 1.01 test and the CLI run the real grader."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from support import utterance, write_clip, write_manifest

from tonekit_harness import adversary, cli, evaluate, manifest, synth
from tonekit_harness.evaluate import EvalError, Result
from tonekit_harness.synth import SynthError

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"
TONE_ERROR = {"tone_swap", "t3_no_dip", "neutral_full"}
NUISANCE = {"noise", "register_shift", "rate"}


@pytest.fixture(scope="module")
def pack_toml() -> str:
    return (PACKS / "cmn.toml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def calib_json() -> str:
    return (PACKS / "cmn.calib.json").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def sources(tmp_path_factory, pack_toml, calib_json) -> list[synth.Source]:
    root = tmp_path_factory.mktemp("adversary-sources")
    made = []
    for cid, tones in [("adv-413", ["4", "1", "3"]), ("adv-152", ["1", "5", "2"])]:
        clip = write_clip(root, cid, 0.5 * utterance(tones), intended=tones, produced=tones)
        made.append(synth.prepare(clip, root=root, pack_toml=pack_toml, calib_json=calib_json))
    return made


def family_of(clip) -> str:
    return clip.synthetic["family"]


def scripted(monkeypatch, score):
    """Replace the grader: `score(clip)` is each trial's `overall` (or raises EvalError)."""

    def grade_pcm(self, clip, pcm, register_json=None):
        overall = score(clip)
        result = Result(
            id=clip.id, set=clip.set, pair=None, label=clip.label, speaker=clip.speaker,
            overall=overall, intended_rank=1, margin_llr=0.0, syllables=[], register_source="cold",
        )  # fmt: skip
        return result, {}

    monkeypatch.setattr(evaluate.Grader, "grade_pcm", grade_pcm)


def hashed(clip) -> float:
    """A stable pseudo-random score in [0, 1) for a clip id."""
    return int(hashlib.sha256(clip.id.encode()).hexdigest()[:8], 16) / 16**8


# ---- the brief's check, with the real grader -----------------------------------------------------


def test_theta_above_one_returns_every_nuisance_trial_as_a_false_reject_and_never_raises(
    sources, tmp_path, monkeypatch
):
    tried = []
    real_perturb = synth.perturb

    def spy(src, family, params, seed):
        made = real_perturb(src, family, params, seed)
        tried.append(made[2])
        return made

    monkeypatch.setattr(synth, "perturb", spy)
    finds = adversary.search(sources, 12, None, seed=4, theta=1.01, out_dir=tmp_path)

    nuisance = [c for c in tried if family_of(c) in NUISANCE]
    assert nuisance and any(family_of(c) in TONE_ERROR for c in tried)  # a real mix, not vacuous
    assert finds.trials == 12 and finds.failed == 0
    assert sorted(c.id for c in finds) == sorted(c.id for c in nuisance)
    assert all(c.label == "correct" and c.needs_listen for c in finds)
    assert finds.false_accepts == 0 and finds.false_rejects == len(nuisance)


# ---- what is a find ---------------------------------------------------------------------------------


def test_a_tone_error_scoring_at_least_theta_is_a_false_accept_and_only_that(
    sources, tmp_path, monkeypatch
):
    scripted(monkeypatch, lambda clip: 0.9)
    finds = adversary.search(sources, 20, None, seed=1, theta=0.9, out_dir=tmp_path)  # 0.9 >= 0.9
    assert finds and all(family_of(c) in TONE_ERROR and c.label == "tone_error" for c in finds)
    assert {c.synthetic["adversary"]["kind"] for c in finds} == {"false_accept"}
    assert finds.false_accepts == len(finds) and finds.false_rejects == 0


def test_a_correct_clip_scoring_below_theta_is_a_false_reject_and_only_that(
    sources, tmp_path, monkeypatch
):
    scripted(monkeypatch, lambda clip: 0.9)
    finds = adversary.search(sources, 20, None, seed=1, theta=0.91, out_dir=tmp_path)
    assert finds and all(family_of(c) in NUISANCE and c.label == "correct" for c in finds)
    assert {c.synthetic["adversary"]["kind"] for c in finds} == {"false_reject"}


def test_no_score_counts_as_a_rejection(sources, tmp_path, monkeypatch):
    scripted(monkeypatch, lambda clip: None)  # "tone not checked"
    finds = adversary.search(sources, 20, None, seed=1, theta=0.0, out_dir=tmp_path)
    assert finds and all(c.label == "correct" for c in finds)  # nothing wrong was accepted


def test_graded_families_are_never_searched(sources, tmp_path, monkeypatch):
    scripted(monkeypatch, lambda clip: 0.5)
    finds = adversary.search(sources, 60, None, seed=2, theta=0.5, out_dir=tmp_path)
    assert finds.trials == 60
    assert {family_of(c) for c in finds} <= TONE_ERROR | NUISANCE
    assert not any(family_of(c) in {"range_compress", "turn_shift", "identity"} for c in finds)


def test_finds_are_ordered_and_carry_their_score_and_theta(sources, tmp_path, monkeypatch):
    scripted(monkeypatch, hashed)
    finds = adversary.search(sources, 40, None, seed=5, theta=0.5, out_dir=tmp_path)

    kinds = [c.synthetic["adversary"]["kind"] for c in finds]
    assert "false_accept" in kinds and "false_reject" in kinds
    assert kinds == sorted(kinds, key=["false_accept", "false_reject"].index)  # accepts first
    accepts = [c for c in finds if c.label == "tone_error"]
    rejects = [c for c in finds if c.label == "correct"]
    assert [(-c.synthetic["adversary"]["score"], c.id) for c in accepts] == sorted(
        (-c.synthetic["adversary"]["score"], c.id) for c in accepts
    )  # score descending, ties by id
    assert [(c.synthetic["adversary"]["score"], c.id) for c in rejects] == sorted(
        (c.synthetic["adversary"]["score"], c.id) for c in rejects
    )  # score ascending
    for c in finds:
        assert c.synthetic["adversary"]["theta"] == 0.5
        assert c.synthetic["adversary"]["score"] == pytest.approx(hashed(c))
        assert c.needs_listen is True
        assert (c.set, c.source) == ("synthetic", "synthetic-world")


def test_an_unscored_reject_sorts_before_every_scored_one(sources, tmp_path, monkeypatch):
    scripted(monkeypatch, lambda clip: None if hashed(clip) < 0.5 else 0.1)
    finds = adversary.search(sources, 30, None, seed=6, theta=0.5, out_dir=tmp_path)
    scores = [c.synthetic["adversary"]["score"] for c in finds]
    assert None in scores and any(s is not None for s in scores)
    assert scores == sorted(scores, key=lambda s: -1.0 if s is None else s)


# ---- robustness and determinism --------------------------------------------------------------------


def test_a_trial_that_fails_inside_tonekit_is_counted_and_skipped(sources, tmp_path, monkeypatch):
    calls, failed_ids = [], []

    def score(clip):
        calls.append(clip.id)
        if len(calls) % 3 == 0:
            failed_ids.append(clip.id)
            raise EvalError(f"{clip.id}: tonekit said no")
        return None

    scripted(monkeypatch, score)
    finds = adversary.search(sources, 12, None, seed=1, theta=0.5, out_dir=tmp_path)
    assert finds.trials == 12 and finds.failed == 4 == len(failed_ids)
    assert finds and not {c.id for c in finds} & set(failed_ids)  # a failed trial leaves no find


def test_the_same_seed_finds_the_same_clips_and_another_seed_others(sources, tmp_path, monkeypatch):
    scripted(monkeypatch, hashed)
    a = adversary.search(sources, 20, None, seed=9, theta=0.5, out_dir=tmp_path / "a")
    b = adversary.search(sources, 20, None, seed=9, theta=0.5, out_dir=tmp_path / "b")
    c = adversary.search(sources, 20, None, seed=10, theta=0.5, out_dir=tmp_path / "c")
    assert [x.id for x in a] == [x.id for x in b]
    assert a == b
    assert [x.id for x in a] != [x.id for x in c]
    assert (tmp_path / "a" / "truth.jsonl").read_text() == (tmp_path / "b" / "truth.jsonl").read_text()


def test_parameters_are_uniform_within_the_bounds_and_custom_bounds_narrow_them(
    sources, tmp_path, monkeypatch
):
    scripted(monkeypatch, lambda clip: None)  # every nuisance trial is a find
    wide = adversary.search(sources, 90, None, seed=3, theta=0.5, out_dir=tmp_path / "w")
    snr = [c.synthetic["params"]["snr_db"] for c in wide if family_of(c) == "noise"]
    shift = [c.synthetic["params"]["st"] for c in wide if family_of(c) == "register_shift"]
    factor = [c.synthetic["params"]["factor"] for c in wide if family_of(c) == "rate"]
    assert snr and shift and factor
    assert all(5 <= x <= 20 for x in snr) and max(snr) - min(snr) > 8
    assert all(-6 <= x <= 6 for x in shift) and min(shift) < 0 < max(shift)
    assert all(0.8 <= x <= 1.25 for x in factor)

    narrow = adversary.search(
        sources, 90, {"noise": {"snr_db": (5.0, 6.0)}, "register_shift": {"st": (-1.0, 1.0)}},
        seed=3, theta=0.5, out_dir=tmp_path / "n",
    )  # fmt: skip
    assert all(5 <= c.synthetic["params"]["snr_db"] <= 6 for c in narrow if family_of(c) == "noise")
    assert all(abs(c.synthetic["params"]["st"]) <= 1 for c in narrow if family_of(c) == "register_shift")


@pytest.mark.parametrize(
    ("bounds", "message"),
    [
        ({"noise": {"snr_db": (0.0, 20.0)}}, r"noise: bounds for snr_db \(0, 20\) must lie inside"),
        ({"rate": {"factor": (0.9, 1.5)}}, r"rate: bounds for factor .* must lie inside"),
        ({"rate": {"factor": (1.2, 1.0)}}, r"rate: bounds for factor .* must lie inside"),
        ({"noise": {"level": (1.0, 2.0)}}, r"noise: no numeric parameter 'level'"),
        ({"teleport": {}}, r"unknown family 'teleport'"),
        ({"range_compress": {"factor": (0.5, 0.6)}}, r"range_compress: not searched"),
    ],
)
def test_custom_bounds_outside_the_spec_are_a_synth_error(sources, tmp_path, bounds, message):
    with pytest.raises(SynthError, match=message):
        adversary.search(sources, 1, bounds, seed=0, theta=0.5, out_dir=tmp_path)


def test_no_sources_is_an_error(tmp_path):
    with pytest.raises(SynthError, match="no sources"):
        adversary.search([], 1, None, seed=0, theta=0.5, out_dir=tmp_path)


# ---- what is written -----------------------------------------------------------------------------------


def test_finds_are_written_as_wavs_a_manifest_and_truth(sources, tmp_path, monkeypatch, pack_toml):
    scripted(monkeypatch, hashed)
    out = tmp_path / "adversarial"
    finds = adversary.search(sources, 20, None, seed=5, theta=0.5, out_dir=out)
    assert finds

    rows = manifest.load(out / "manifest.jsonl")
    assert rows == list(finds)
    truth = [json.loads(line) for line in (out / "truth.jsonl").read_text().splitlines()]
    assert [t["id"] for t in truth] == [c.id for c in finds]
    assert sorted(p.name for p in (out / "wav").iterdir()) == sorted(f"{c.id}.wav" for c in finds)
    _, pcm = evaluate.read_wav(out / rows[0].path, rows[0].id)
    assert len(pcm) > 0 and len(truth[0]["f0_hz"]) == len(pcm) // 160 + 1


def test_a_search_that_finds_nothing_writes_empty_files(sources, tmp_path):
    finds = adversary.search(sources, 0, None, seed=0, theta=0.5, out_dir=tmp_path)
    assert list(finds) == [] and finds.trials == 0
    assert (tmp_path / "manifest.jsonl").read_text() == ""
    assert (tmp_path / "truth.jsonl").read_text() == ""


# ---- tkh adversary --------------------------------------------------------------------------------------


def test_tkh_adversary_prints_a_summary_and_exits_zero(tmp_path, capsys):
    src_root = tmp_path / "corpus"
    src_root.mkdir()
    clip = write_clip(
        src_root, "cli-413", 0.5 * utterance(["4", "1", "3"]), intended=["4", "1", "3"],
        produced=["4", "1", "3"],
    )  # fmt: skip
    m = write_manifest(src_root / "manifest.jsonl", [clip])
    out = tmp_path / "adversarial"

    code = cli.main(
        ["adversary", "--manifest", str(m), "--pack", str(PACKS / "cmn.toml"),
         "--calib", str(PACKS / "cmn.calib.json"), "--trials", "4", "--theta", "1.01",
         "--out", str(out), "--seed", "2"]
    )  # fmt: skip
    assert code == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert line.startswith("adversary: 4 trials (0 failed), 0 false accepts, ")
    assert "false rejects" in line and str(out) in line
    assert (out / "manifest.jsonl").exists() and (out / "truth.jsonl").exists()


def test_tkh_adversary_exits_zero_even_when_it_finds_nothing(tmp_path, capsys):
    src_root = tmp_path / "corpus"
    src_root.mkdir()
    clip = write_clip(
        src_root, "cli-413", 0.5 * utterance(["4", "1", "3"]), intended=["4", "1", "3"],
        produced=["4", "1", "3"],
    )  # fmt: skip
    m = write_manifest(src_root / "manifest.jsonl", [clip])
    code = cli.main(
        ["adversary", "--manifest", str(m), "--pack", str(PACKS / "cmn.toml"), "--trials", "0",
         "--theta", "0.5", "--out", str(tmp_path / "o")]
    )  # fmt: skip
    assert code == 0
    assert "0 trials (0 failed), 0 false accepts, 0 false rejects" in capsys.readouterr().out


def test_tkh_adversary_reports_errors_and_exits_non_zero(tmp_path, capsys):
    code = cli.main(
        ["adversary", "--manifest", str(tmp_path / "missing.jsonl"), "--pack",
         str(PACKS / "cmn.toml"), "--trials", "1", "--theta", "0.5", "--out", str(tmp_path / "o")]
    )  # fmt: skip
    assert code == 1
    assert "error:" in capsys.readouterr().err
