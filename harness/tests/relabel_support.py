"""A small volunteer corpus for the review and relabel tests (synthetic clips of real deck cards,
taken in by intake), and review-page exports to apply to it."""

from __future__ import annotations

import json
from pathlib import Path

from intake_support import kit_bundle, options

from tonekit_harness import clearance, manifest
from tonekit_harness.contracts.relabel import RelabelExport, load_log
from tonekit_harness.eval_results import SCHEMA, EvalResults
from tonekit_harness.intake.run import intake_bundle
from tonekit_harness.relabel.apply import Outcome, relabel_corpus
from tonekit_harness.repo import repo_root

CORPUS = "volunteers-s05-v1"
CODE = "K7Q2MD"
# two gate pairs, a diag_t23 pair, a register card and a minimal-set member
CARDS = ["g01-c", "g01-e", "g02-c", "g02-e", "t01-c", "t01-e", "r01", "m01-a"]
WHEN = "2026-10-07T12:00:00Z"


def corpus_dir(root: Path) -> Path:
    return root / "corpora" / CORPUS


def manifest_file(root: Path) -> Path:
    return corpus_dir(root) / "manifest.jsonl"


def make_corpus(tmp_path: Path, codes: tuple[str, ...] = (CODE,), *, voiced: bool = False) -> Path:
    """A data root with one session per code, each reading `CARDS`."""
    root = tmp_path / "data"
    for code in codes:
        intake_bundle(kit_bundle(tmp_path / "in", code, CARDS, voiced=voiced), options(root))
    return root


def rows(root: Path) -> dict[str, manifest.Clip]:
    """The manifest's rows by clip id (every row validates)."""
    return {c.id: c for c in manifest.load(manifest_file(root), register=clearance.read_register(None))}


def decision(clip: str, verdict: str, tones: list[str] | None = None, at: str = WHEN) -> dict:
    return {"clip": clip, "verdict": verdict, "tones": tones, "decided_at": at}


def export(*decisions: dict, corpus: str = CORPUS, who: str = "DJ") -> RelabelExport:
    return RelabelExport.model_validate(
        {"schema": "tonekit.relabels.v1", "corpus": corpus, "who": who, "exported_at": WHEN, "decisions": list(decisions)}
    )


def export_file(where: Path, *decisions: dict, corpus: str = CORPUS) -> Path:
    path = where / f"relabels-{corpus}.json"
    path.write_text(export(*decisions, corpus=corpus).model_dump_json(by_alias=True), encoding="utf-8")
    return path


def relabel(root: Path, *decisions: dict, corpus: str = CORPUS) -> Outcome:
    return relabel_corpus(
        root,
        CORPUS,
        export(*decisions, corpus=corpus),
        repo=repo_root(),
        register=clearance.read_register(None),
        source="relabels-test.json",
    )


def log_entries(root: Path) -> list:
    return load_log(corpus_dir(root) / "relabels.jsonl")


def log_lines(root: Path) -> list[dict]:
    path = corpus_dir(root) / "relabels.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def results_file(root: Path, heard: dict[str, list[str | None]]) -> Path:
    """A `tkh eval --results` file at the default place, grading the clips in `heard` (clip id ->
    the tone heard per syllable, None for unsure): p_correct is 0.9 where the intended tone was
    heard, 0.5 where nothing was, 0.05 elsewhere. Clips not in `heard` are not graded."""
    by_id = rows(root)
    clips = []
    for cid, tones in heard.items():
        row = by_id[cid]
        syllables = [
            {
                "expected": intended,
                "heard": h,
                "p_correct": 0.5 if h is None else 0.9 if h == intended else 0.05,
                "distance": 1.0,
                "measured": "Full",
            }
            for h, intended in zip(tones, row.intended.tones, strict=True)
        ]
        clips.append({"id": cid, "set": row.set, "pair": row.pair, "label": row.label, "speaker": row.speaker,
                      "overall": min(s["p_correct"] for s in syllables), "intended_rank": 1, "margin_llr": 0.0,
                      "register_source": "cold", "syllables": syllables})  # fmt: skip
    doc = EvalResults.model_validate({"schema": SCHEMA, "register_from": "drill", "tonekit_py": "test", "clips": clips})
    path = root / "reports" / f"{CORPUS}.results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc.model_dump_json(by_alias=True), encoding="utf-8")
    return path
