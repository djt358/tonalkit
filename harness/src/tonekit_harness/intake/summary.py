"""What `tkh intake` prints: per bundle, what it did; then, per corpus, the `tkh eval` command to
run next, its report under the data root (a report lists clips by session code)."""

from __future__ import annotations

import shlex
from collections.abc import Mapping
from pathlib import Path

from ..contracts.registry import speaker_accent
from ..evaluate import base_accent
from . import layout
from .run import IntakeResult


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _accent_note(r: IntakeResult) -> list[str]:
    graded = base_accent(r.pack.read_text(encoding="utf-8"))
    own = speaker_accent(r.speaker, r.lect)
    if own == graded:
        return []
    return [
        f"  note: {r.speaker.id}'s default accent is {own}; tkh eval grades every clip against one "
        f"accent (default {graded}): add --accent {own} to grade this speaker against theirs"
    ]


def _register_note(r: IntakeResult, register: Mapping[str, str]) -> list[str]:
    if register.get(r.source) == "allow":
        return []
    return [f"  note: data-register.csv does not allow {r.source!r}; tkh eval will call the run NOT A GATE"]


def bundle_lines(r: IntakeResult, register: Mapping[str, str]) -> list[str]:
    kept = sum(r.per_set.values())
    sets = ", ".join(f"{name} {n}" for name, n in r.per_set.items())
    lines = [
        f"intake {r.code} ({r.bundle})",
        f"  deck: {r.deck_where}",
        f"  corpus: {r.corpus_id} ({'new' if r.created else 'existing'}) at {r.corpus}",
        f"  speaker: {r.speaker.id}, split {r.speaker.split}",
        f"  clips kept: {kept} ({sets})",
        f"  skipped by the speaker: {len(r.skipped)}" + (f" ({', '.join(r.skipped)})" if r.skipped else ""),
    ]
    if r.kept_out:
        lines.append(f"  kept out: {_plural(len(r.kept_out), 'recorded card')}, no row and no audio")
        lines += [f"    {card}: {why}" for card, why in r.kept_out.items()]
    return lines + _accent_note(r) + _register_note(r, register)


def eval_command(manifest: Path, pack: Path, report: Path) -> str:
    args = ["uv", "run", "tkh", "eval", "--manifest", manifest, "--pack", pack, "--report", report]
    return " ".join(shlex.quote(str(a)) for a in args)


def next_lines(results: list[IntakeResult], root: Path) -> list[str]:
    """One `tkh eval` command per corpus the bundles went into (run from harness/)."""
    by_corpus = {r.corpus_id: r for r in results}
    lines = ["", "next, from harness/ (the report goes under the data root, never the repository):"]
    for cid, r in by_corpus.items():
        lines.append("  " + eval_command(r.manifest, r.pack, layout.report_path(root, cid)))
    return lines
