"""`tkh fit` (rulings R103, R108, R109): what it may fit on, what it fits and what it writes. Synthetic
speech only (tests/support.py)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
import tonekit_py

from tonekit_harness import cli
from tonekit_harness.fit import cli as fit_cli
from tonekit_harness.evaluate import Grader
from tonekit_harness.fit.observe import SHAPE, UNPITCHED, Observation, observe_clip
from tonekit_harness.fit.select import FitError, calib_speakers, fit_clips
from tonekit_harness.fit.tail import fit_creaky_tail, tail_rates
from tonekit_harness.fit.unpitched import MIN_HITS, MIN_RATE, SMOOTHING, fit_unpitched, rates

from support import gate_corpus, write_manifest

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"
TONES = ["1", "2", "3", "4", "5"]


def corpus_toml(path: Path, splits: dict[str, str]) -> Path:
    speakers = "".join(f'\n[[speaker]]\nid = "{s}"\nsplit = "{split}"\n' for s, split in splits.items())
    path.write_text(
        '[corpus]\nid = "synthetic-fit"\nsource = "synthetic-world"\nkind = "recorded"\nlect = "cmn"\n'
        + speakers,
        encoding="utf-8",
    )
    return path


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    clips = gate_corpus(root)
    write_manifest(root / "manifest.jsonl", clips)
    return root, clips


def fit_args(root: Path, out: Path, *extra: str) -> list[str]:
    return [
        "fit",
        "--manifest", str(root / "manifest.jsonl"),
        "--pack", str(PACKS / "cmn.toml"),
        "--calib", str(PACKS / "cmn.calib.json"),
        "--out-calib", str(out),
        "--rounds", "1",
        *extra,
    ]  # fmt: skip


def test_only_calib_speakers_are_fitted_on(corpus, tmp_path):
    root, clips = corpus
    toml = corpus_toml(root / "corpus.toml", {"dj": "gate", "other": "calib"})
    assert calib_speakers(toml) == ["other"]
    with pytest.raises(FitError, match="not in the calib split"):
        fit_clips(clips, ["other"], ["dj"])
    with pytest.raises(FitError, match="no clips"):
        fit_clips(clips, ["other"], None)
    assert fit_clips(clips, ["dj"], None) == clips


def test_tkh_fit_refuses_a_gate_speaker(corpus, tmp_path, capsys):
    root, _ = corpus
    corpus_toml(root / "corpus.toml", {"dj": "gate"})
    out = tmp_path / "fitted.calib.json"
    assert cli.main(fit_args(root, out)) == 1
    assert "no speaker of the corpus is in the calib split" in capsys.readouterr().err
    assert cli.main(fit_args(root, out, "--speaker", "dj")) == 1
    assert "dj are not in the calib split" in capsys.readouterr().err
    assert not out.exists()


def test_tkh_fit_writes_a_calibration_tonekit_loads(corpus, tmp_path):
    root, _ = corpus
    corpus_toml(root / "corpus.toml", {"dj": "calib"})
    out = tmp_path / "fitted.calib.json"
    assert cli.main(fit_args(root, out)) == 0
    fitted = json.loads(out.read_text(encoding="utf-8"))
    seed = json.loads((PACKS / "cmn.calib.json").read_text(encoding="utf-8"))
    evidence = ("unpitched", "creaky_tail")
    assert {k: v for k, v in fitted.items() if k not in evidence} == {
        k: v for k, v in seed.items() if k not in evidence
    }
    for section in evidence:
        for place in ("phrase_final", "other"):
            assert sorted(fitted[section][place]) == TONES
            assert all(v <= 0 for v in fitted[section][place].values())
    # tonekit accepts it: a lattice of silence loads the pack with it.
    analysis = tonekit_py.analyze([0.0] * 1600, 16000)
    grading = json.dumps({"accent": "cmn-standard", "style": None, "style_weight": 0.0})
    tonekit_py.lattice(analysis, (PACKS / "cmn.toml").read_text(encoding="utf-8"), out.read_text(encoding="utf-8"), grading)


def test_a_fit_starts_without_the_start_calibrations_evidence(corpus, monkeypatch):
    # The first round observes without the unpitched and creaky-tail evidence of the calibration
    # it starts from (fitted earlier, perhaps on other speakers); the second with round one's.
    root, clips = corpus
    seen = []
    real = fit_cli.observations

    def spy(clips, pack_toml, calib_json, *args, **kwargs):
        seen.append(json.loads(calib_json))
        return real(clips, pack_toml, calib_json, *args, **kwargs)

    monkeypatch.setattr(fit_cli, "observations", spy)
    start = json.loads((PACKS / "cmn.calib.json").read_text(encoding="utf-8"))
    planted = {"phrase_final": {t: -0.1 for t in TONES}, "other": {t: -0.1 for t in TONES}}
    for section in fit_cli.FITTED_SECTIONS:
        start[section] = planted
    pack = (PACKS / "cmn.toml").read_text(encoding="utf-8")
    fitted = fit_cli.fit(clips, pack, json.dumps(start), root, rounds=2, templates=False)
    assert len(seen) == 2
    assert not set(fit_cli.FITTED_SECTIONS) & set(seen[0])
    assert all(seen[1][section] not in (None, planted) for section in fit_cli.FITTED_SECTIONS)
    assert all(fitted.calib[section] != planted for section in fit_cli.FITTED_SECTIONS)
    assert seen[0] == {k: v for k, v in start.items() if k not in fit_cli.FITTED_SECTIONS}


def test_tkh_fit_writes_a_fitted_pack_and_refuses_a_component_weight_out_of_range(corpus, tmp_path, capsys):
    root, _ = corpus
    corpus_toml(root / "corpus.toml", {"dj": "calib"})
    out, pack = tmp_path / "fitted.calib.json", tmp_path / "fitted.toml"
    assert cli.main(fit_args(root, out, "--out-pack", str(pack), "--as-component", "1.5")) == 1
    assert "--as-component must be between 0 and 1" in capsys.readouterr().err
    assert not out.exists() and not pack.exists()
    args = fit_args(root, out, "--out-pack", str(pack), "--as-component", "0.5", "--shrink", "5")
    assert cli.main(args) == 0
    text = pack.read_text(encoding="utf-8")
    assert text.startswith("# cmn pack, fitted by `tkh fit` (ruling R109)")
    grading = json.dumps({"accent": "cmn-standard", "style": None, "style_weight": 0.0})
    tonekit_py.lattice(tonekit_py.analyze([0.0] * 1600, 16000), text, out.read_text(encoding="utf-8"), grading)


def obs(tone: str, kind: str, final: bool = True, creaky: bool = False) -> Observation:
    return Observation("c", "s", "correct", True, tone, 0, 1, None, final, kind, None, creaky)


def test_creaky_tail_rates_count_only_syllables_with_a_shape():
    # Tone 4 at the phrase's end: 12 of 16 shapes end in creak; tone 1: none of 16; an unpitched
    # tone 4 and an error card's creaky tone 1 are not counted.
    error = Observation("e", "s", "tone_error", True, "1", 0, 1, None, True, SHAPE, None, True)
    observations = (
        [obs("4", SHAPE, creaky=True)] * 12
        + [obs("4", SHAPE)] * 4
        + [obs("4", UNPITCHED), error]
        + [obs("1", SHAPE)] * 16
    )
    r = tail_rates(observations, TONES, final=True)
    pooled = (12 + 1) / (32 + 2)
    assert r["4"] == pytest.approx((12 + SMOOTHING * pooled) / (16 + SMOOTHING))
    assert r["1"] == pytest.approx((0 + SMOOTHING * pooled) / (16 + SMOOTHING))
    fitted = fit_creaky_tail(observations, TONES)
    assert fitted["phrase_final"]["4"] == round(math.log(r["4"]), 4)
    assert fitted["other"]["4"] == round(math.log(0.5), 4)  # nothing there: Laplace's 1/2


def test_unpitched_rates_are_smoothed_towards_the_pooled_rate():
    # Tone 3: 12 unpitched of 16 at the phrase's end; tone 1: 0 of 16; pooled by Laplace:
    # (12 + 1) / (32 + 2).
    observations = [obs("3", UNPITCHED)] * 12 + [obs("3", SHAPE)] * 4 + [obs("1", SHAPE)] * 16
    r = rates(observations, TONES, final=True)
    pooled = 13 / 34
    assert r["3"] == pytest.approx((12 + SMOOTHING * pooled) / (16 + SMOOTHING))
    assert r["1"] == pytest.approx((0 + SMOOTHING * pooled) / (16 + SMOOTHING))
    assert r["2"] == pytest.approx(pooled)
    # Nothing elsewhere in the phrase: Laplace's 1/2.
    assert rates(observations, TONES, final=False)["3"] == pytest.approx(0.5)
    fitted = fit_unpitched(observations, TONES)
    assert fitted["phrase_final"]["3"] == round(math.log(r["3"]), 4)
    assert min(fitted["phrase_final"].values()) >= round(math.log(MIN_RATE), 4)


def test_a_place_with_few_hits_gives_every_tone_the_pooled_rate():
    # 3 unpitched tone 3s of 4, none of 16 tone 1s: too few hits to tell the tones apart, so the
    # table is flat there (every tone at the pooled rate) and says nothing for or against a tone.
    few = [obs("3", UNPITCHED)] * 3 + [obs("3", SHAPE)] + [obs("1", SHAPE)] * 16
    r = rates(few, TONES, final=True)
    assert list(r.values()) == pytest.approx([(3 + 1) / (20 + 2)] * len(TONES))
    # One hit short of `MIN_HITS` is still flat; at `MIN_HITS` the tones part.
    short = [obs("3", UNPITCHED)] * (MIN_HITS - 1) + [obs("1", SHAPE)] * 16
    assert len(set(rates(short, TONES, final=True).values())) == 1
    enough = [obs("3", UNPITCHED)] * MIN_HITS + [obs("1", SHAPE)] * 16
    r = rates(enough, TONES, final=True)
    assert r["3"] > r["2"] > r["1"]
    # The creaky-tail table shares the rule.
    tails = [obs("4", SHAPE, creaky=True)] * 3 + [obs("1", SHAPE)] * 16
    assert len(set(tail_rates(tails, TONES, final=True).values())) == 1


def test_missed_syllables_say_nothing_about_creak():
    observations = [obs("3", UNPITCHED), obs("3", "missed"), obs("3", "missed")]
    assert rates(observations, ["3"], final=True) == rates(observations[:1], ["3"], final=True)


def test_observations_follow_the_produced_reading(corpus):
    root, clips = corpus
    pack = (PACKS / "cmn.toml").read_text(encoding="utf-8")
    calib = (PACKS / "cmn.calib.json").read_text(encoding="utf-8")
    grader = Grader(pack, calib, "cmn-standard", root, None)
    error = next(c for c in clips if c.id == "gate-01-error")
    seen = observe_clip(error, grader, None)
    assert [o.tone for o in seen] == ["4", "2", "3"]  # what was spoken, not the card's 4-1-3
    assert [o.prev for o in seen] == [None, "4", "2"]
    assert [o.final for o in seen] == [False, False, True]
    assert all(o.kind == SHAPE and o.shape is not None and len(o.shape["contour"]) == 10 for o in seen)
