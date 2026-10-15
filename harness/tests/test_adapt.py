"""`tkh adapt` on tiny synthetic downloads of AISHELL-3 and THCHS-30 in their own layouts: the corpus
it writes (contracts §3, §4), what it drops and why (R122), the licence refusal, hashed splits,
atomic writes and idempotence."""

from __future__ import annotations

import csv
import io
import json

import pytest
from adapt_support import (
    AISHELL_SPEAKERS,
    AISHELL_UTTERANCES,
    THCHS_UTTERANCES,
    aishell3_download,
    thchs30_download,
)
from intake_support import tkh, tree
from relabel_support import decision, export_file
from scipy.io import wavfile

from tonekit_harness import clearance, manifest
from tonekit_harness.adapt import aishell3, drops, thchs30
from tonekit_harness.adapt.corpus_files import AdaptError
from tonekit_harness.adapt.run import AdaptOptions, adapt
from tonekit_harness.contracts.registry import StaleMarker, hashed_split, load_corpus_file
from tonekit_harness.repo import repo_root


def options(data, **overrides) -> AdaptOptions:
    base = {"root": data, "repo": repo_root(), "register": clearance.read_register(None)}
    return AdaptOptions(**{**base, **overrides})


def rows(data, corpus: str) -> dict[str, manifest.Clip]:
    return {c.id: c for c in manifest.load(data / "corpora" / corpus / "manifest.jsonl")}


def kept(table: dict) -> set[str]:
    return {uid for uid, entry in table.items() if entry[-1] is None}


# ---- AISHELL-3 ---------------------------------------------------------------------------------


@pytest.fixture
def aishell(tmp_path):
    return aishell3_download(tmp_path / "download")


def test_aishell3_becomes_a_public_corpus_of_sentences(aishell, tmp_path, capsys):
    data = tmp_path / "data"
    code, out, err = tkh(capsys, "adapt", "aishell3", str(aishell), "--data", str(data), "--max-syllables", "5")
    assert code == 0, err
    corpus = data / "corpora" / "aishell3"
    meta = load_corpus_file(corpus / "corpus.toml")
    assert (meta.corpus.kind, meta.corpus.source, meta.corpus.lect) == ("public", "aishell-3", "cmn")
    found = rows(data, "aishell3")
    assert set(found) == kept(AISHELL_UTTERANCES)
    for row in found.values():
        assert (row.set, row.label, row.pair, row.context) == ("sentence", "correct", None, "phrase")
        assert row.source == "aishell-3"
        assert row.produced_tones == row.intended.tones and row.distractors == []
        assert row.speaker == row.id[:7] and row.path == f"audio/{row.speaker}/{row.id}.wav"
        rate, samples = wavfile.read(corpus / row.path)
        assert (rate, samples.ndim, str(samples.dtype)) == (16_000, 1, "int16")
    assert found["SSB00050002"].produced_tones == ["2", "4", "2"]
    assert found["SSB00050002"].intended.labels == ["yi", "ge", "ren"]
    assert "-> corpus aishell3: created" in out and "12 read, 4 kept as sentence rows, 8 dropped" in out


def test_aishell3_speakers_carry_what_the_corpus_says_and_their_hashed_split(aishell, tmp_path):
    adapt(aishell3, aishell, options(tmp_path / "data"))
    speakers = {s.id: s for s in load_corpus_file(tmp_path / "data/corpora/aishell3/corpus.toml").speaker}
    assert set(speakers) == set(AISHELL_SPEAKERS)
    for sid, s in speakers.items():
        assert s.split == hashed_split(sid) and s.accent is None and s.background == "native"
    assert (speakers["SSB0005"].grew_up_hearing, speakers["SSB0011"].grew_up_hearing) == ("mainland", "mainland")
    assert speakers["SSB0012"].grew_up_hearing is None  # accent "others"
    assert {s.split for s in speakers.values()} == {"heldout", "calib"}


def test_aishell3_drops_are_counted_by_reason(aishell, tmp_path):
    result = adapt(aishell3, aishell, options(tmp_path / "data", max_syllables=5))
    counts = result.plan.dropped.counts
    assert counts == {
        drops.THIRD_TONES: 1, drops.ERHUA: 1, drops.MANY_READINGS: 1, drops.MALFORMED: 1, drops.NO_AUDIO: 1,
        drops.NEUTRAL_YI_BU: 1, drops.TOO_LONG: 1, drops.BAD_AUDIO: 1,
    }  # fmt: skip
    for uid, (_, _, outcome) in AISHELL_UTTERANCES.items():
        if outcome is not None:
            reason = next(r for r, ids in result.plan.dropped.examples.items() if uid in ids)
            assert outcome in reason, (uid, reason)


def test_max_syllables_keeps_longer_utterances_when_raised(aishell, tmp_path):
    result = adapt(aishell3, aishell, options(tmp_path / "data", max_syllables=6))
    assert "SSB00120002" in rows(tmp_path / "data", "aishell3") and drops.TOO_LONG not in result.plan.dropped.counts


def test_limit_speakers_takes_the_first_by_id(aishell, tmp_path):
    result = adapt(aishell3, aishell, options(tmp_path / "data", limit_speakers=1))
    assert result.plan.speakers == ["SSB0005"] and result.plan.speakers_in_corpus == 3
    assert {r.speaker for r in rows(tmp_path / "data", "aishell3").values()} == {"SSB0005"}


# ---- the licence --------------------------------------------------------------------------------


def register_with(tmp_path, source: str, value: str | None) -> str:
    """A copy of the data register with `source`'s shipped_weights_training set to `value`, or
    without its row."""
    text = clearance.default_register().read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=reader.fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in reader:
        if row["id"] == source:
            if value is None:
                continue
            row["shipped_weights_training"] = value
        writer.writerow(row)
    path = tmp_path / "register.csv"
    path.write_text(out.getvalue(), encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("value", ["deny", "verify", None])
def test_a_source_the_register_does_not_allow_is_refused_with_nothing_written(aishell, tmp_path, capsys, value):
    data = tmp_path / "data"
    register = register_with(tmp_path, "aishell-3", value)
    code, _, err = tkh(capsys, "adapt", "aishell3", str(aishell), "--data", str(data), "--register", register)
    assert code == 1 and "source 'aishell-3'" in err and "only 'allow' may be adapted" in err
    assert not data.exists()


def test_the_registers_denied_corpora_stay_denied():
    register = clearance.read_register(None)
    assert register["magicdata-read"] == "deny"
    assert all(register[m.SOURCE] == "allow" for m in (aishell3, thchs30))


# ---- atomic and idempotent ---------------------------------------------------------------------


def test_adapting_the_same_download_again_changes_nothing(aishell, tmp_path, capsys):
    data = tmp_path / "data"
    assert tkh(capsys, "adapt", "aishell3", str(aishell), "--data", str(data))[0] == 0
    before = tree(data)
    code, out, err = tkh(capsys, "adapt", "aishell3", str(aishell), "--data", str(data))
    assert code == 0, err
    assert "-> corpus aishell3: unchanged" in out
    assert tree(data) == before  # no staging left, no stale marker


def test_adapting_with_other_options_replaces_the_corpus_and_marks_it_stale(aishell, tmp_path):
    data = tmp_path / "data"
    adapt(aishell3, aishell, options(data))
    result = adapt(aishell3, aishell, options(data, limit_speakers=1))
    assert result.outcome == "replaced"
    assert {r.speaker for r in rows(data, "aishell3").values()} == {"SSB0005"}
    marker = StaleMarker.model_validate_json((data / "stale" / "aishell3.json").read_text())
    assert [r.reason for r in marker.reasons] == ["adapted again from aishell3 (2 clips)"]
    assert sorted(p.name for p in (data / "corpora").iterdir()) == ["aishell3"]  # nothing set aside is left


def test_a_failure_while_staging_leaves_the_data_root_as_it_was(aishell, tmp_path, monkeypatch):
    data = tmp_path / "data"
    adapt(aishell3, aishell, options(data))
    before = tree(data)

    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("tonekit_harness.adapt.run.check_new_files", broken)
    with pytest.raises(OSError, match="disk full"):
        adapt(aishell3, aishell, options(data, limit_speakers=1))
    assert tree(data) == before


def test_leftovers_of_a_killed_run_are_cleared_but_not_another_corpuss(aishell, tmp_path):
    data = tmp_path / "data"
    mine, theirs = data / "corpora" / ".adapt-aishell3-999", data / "corpora" / ".adapt-aishell3-x-999"
    for d in (mine, theirs):
        (d / "audio").mkdir(parents=True)
    adapt(aishell3, aishell, options(data))
    assert not mine.exists() and theirs.exists()


def test_an_existing_corpus_of_another_kind_or_source_is_not_replaced(aishell, tmp_path):
    data = tmp_path / "data"
    adapt(thchs30, thchs30_download(tmp_path / "t"), options(data, corpus_id="aishell3"))
    with pytest.raises(AdaptError, match="not public from 'aishell-3'"):
        adapt(aishell3, aishell, options(data))
    (data / "corpora" / "other").mkdir()
    (data / "corpora" / "other" / "notes.txt").write_text("mine")
    with pytest.raises(AdaptError, match="has no corpus.toml"):
        adapt(aishell3, aishell, options(data, corpus_id="other"))


def test_a_corpus_with_relabels_is_not_replaced(aishell, tmp_path):
    data = tmp_path / "data"
    adapt(aishell3, aishell, options(data))
    (data / "corpora" / "aishell3" / "relabels.jsonl").write_text("{}\n")
    with pytest.raises(AdaptError, match="would lose them"):
        adapt(aishell3, aishell, options(data, limit_speakers=1))


@pytest.mark.parametrize("bad", [{"max_syllables": 0}, {"limit_speakers": 0}, {"corpus_id": "Not/Valid"}])
def test_bad_options_are_refused(aishell, tmp_path, bad):
    with pytest.raises(AdaptError):
        adapt(aishell3, aishell, options(tmp_path / "data", **bad))
    assert not (tmp_path / "data").exists()


def test_a_wrong_directory_is_refused_with_a_hint(aishell, tmp_path, capsys):
    code, _, err = tkh(capsys, "adapt", "aishell3", str(aishell.parent), "--data", str(tmp_path / "data"))
    assert code == 1 and "pass the data_aishell3 directory" in err
    code, _, err = tkh(capsys, "adapt", "thchs30", str(aishell), "--data", str(tmp_path / "data"))
    assert code == 1 and "needs data/ and train/, dev/ or test/" in err


# ---- THCHS-30 ----------------------------------------------------------------------------------


def test_thchs30_is_read_as_a_script_transcript_with_word_boundaries(tmp_path):
    data = tmp_path / "data"
    result = adapt(thchs30, thchs30_download(tmp_path / "download"), options(data))
    found = rows(data, "thchs30")
    assert set(found) == kept(THCHS_UTTERANCES)
    assert found["A11_1"].produced_tones == ["2", "4", "2", "3"]  # 不对 你好 through the checker
    assert found["C4_0"].produced_tones == ["1", "5", "4", "3"]
    assert result.plan.dropped.counts == {
        drops.T3_ACROSS_WORDS: 1, drops.YI_BU_DICTIONARY: 1, drops.MIXED: 1, drops.MALFORMED: 1, drops.NO_TRANSCRIPT: 1,
    }  # fmt: skip
    speakers = {s.id: s for s in load_corpus_file(data / "corpora" / "thchs30" / "corpus.toml").speaker}
    assert {sid: s.split for sid, s in speakers.items()} == {"A11": "calib", "C4": "heldout"}  # B4 kept nothing
    assert all(s.background is None and s.grew_up_hearing is None for s in speakers.values())


# ---- what comes next: tkh eval and tkh fit ------------------------------------------------------


def test_an_adapted_corpus_is_graded_without_a_verdict_and_fitted_on_its_calib_speakers(aishell, tmp_path, capsys):
    data = tmp_path / "data"
    code, out, err = tkh(capsys, "adapt", "aishell3", str(aishell), "--data", str(data))
    assert code == 0, err
    fit_line, eval_line = [line.strip() for line in out.splitlines() if line.startswith("  uv run tkh ")]
    fit_args, eval_args = fit_line.split()[3:], eval_line.split()[3:]
    assert eval_args[eval_args.index("--speaker") + 1] == "SSB0005"  # the held-out speaker
    code, out, err = tkh(capsys, *fit_args, "--rounds", "1")
    assert code == 0, err
    assert "fitted on 3 clips of SSB0011, SSB0012" in out
    assert json.loads((data / "fits" / "aishell3.calib.json").read_text())["unpitched"]
    code, out, err = tkh(capsys, *eval_args, "--no-cache")
    assert code == 0, err
    assert out.startswith("S1: no verdict (no gate clips)")
    report = (data / "reports" / "aishell3.md").read_text(encoding="utf-8")
    assert "- clips: sentence 2" in report


def test_a_sentence_relabelled_by_a_listener_stays_one_correct_reading(aishell, tmp_path, capsys):
    data = tmp_path / "data"
    adapt(aishell3, aishell, options(data))
    file = export_file(tmp_path, decision("SSB00050001", "heard", ["3", "3"]), corpus="aishell3")
    code, _, err = tkh(capsys, "relabel", str(file), "--corpus", "aishell3", "--data", str(data))
    assert code == 0, err
    row = rows(data, "aishell3")["SSB00050001"]
    assert (row.label, row.produced_tones, row.intended.tones) == ("correct", ["3", "3"], ["3", "3"])
    with pytest.raises(AdaptError, match="would lose them"):  # and adapting again would undo it
        adapt(aishell3, aishell, options(data, limit_speakers=1))
