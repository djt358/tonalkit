"""What `tkh adapt` prints: what it wrote, what it dropped and why (R122), and the commands to run
next (`tkh fit` on the calib speakers, `tkh eval` on the held-out ones; reports go under the data
root)."""

from __future__ import annotations

import shlex
from pathlib import Path

from ..intake import layout as data_layout
from .run import AdaptResult

SPLIT_ORDER = ("calib", "dev", "heldout", "gate")


def _quoted(args: list[object]) -> str:
    return " ".join(shlex.quote(str(a)) for a in args)


def result_lines(r: AdaptResult) -> list[str]:
    p = r.plan
    splits = ", ".join(f"{s} {len(r.splits[s])}" for s in SPLIT_ORDER if s in r.splits)
    chosen = str(len(p.speakers))
    if len(p.speakers) < p.speakers_in_corpus:
        chosen += f" of {p.speakers_in_corpus}"
    lines = [
        f"adapt {r.adapter} ({r.src}) -> corpus {r.corpus_id}: {r.outcome} at {r.corpus}",
        f"  source: {r.source} (public)",
        f"  speakers: {chosen} read; {sum(len(ids) for ids in r.splits.values())} kept ({splits})",
        f"  utterances: {p.utterances} read, {r.kept} kept as sentence rows, {p.dropped.total} dropped",
    ]
    for reason, n in p.dropped.counts.most_common():
        lines.append(f"    {n:>7}  {reason} (e.g. {', '.join(p.dropped.examples[reason])})")
    if r.stale is not None:
        lines.append(f"  marked stale: {r.stale} (anything fitted on the old corpus must be refitted)")
    return lines


def next_lines(r: AdaptResult, root: Path) -> list[str]:
    """`tkh fit` on the corpus's calib speakers, then `tkh eval` of that calibration on its
    held-out speakers (run from harness/), registers pooled from each speaker's clips: public
    speakers have no register drill."""
    report, results = data_layout.report_path(root, r.corpus_id), data_layout.results_path(root, r.corpus_id)
    calib = root / "fits" / f"{r.corpus_id}.calib.json"
    data = ["--data", root]
    fit = ["uv", "run", "tkh", "fit", *data, "--select", f"{r.corpus_id}:calib", "--pack", r.pack, "--out-calib", calib]
    fit += ["--register-from", "speaker"]
    lines = ["", "next, from harness/ (outputs go under the data root, never the repository):", "  " + _quoted(fit)]
    held_out = r.splits.get("heldout", [])
    if held_out:
        evaluate = ["uv", "run", "tkh", "eval", *data, "--select", f"{r.corpus_id}:heldout", "--pack", r.pack]
        evaluate += ["--calib", calib, "--register-from", "speaker", "--report", report, "--results", results]
        lines.append("  " + _quoted(evaluate))
    return lines
