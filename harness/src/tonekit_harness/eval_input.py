"""Where `tkh eval` gets its clips: one manifest (`--manifest`, clip paths relative to its
directory, one accent for every speaker) or a selection across the corpora under the data root
(`--select`, speakers `corpus/speaker`, each graded against their own accent unless `--accent`
says otherwise, R82)."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from . import clearance, manifest
from .data_option import root_from
from .manifest import Clip
from .registry import Refusal
from .registry.runs import accent_summary, describe, gate_clearance, selection_from


class NoClipsError(ValueError):
    """`--speaker` left no clip of a manifest to grade."""


@dataclass(frozen=True)
class EvalInput:
    clips: list[Clip]
    root: Path  # the clips' paths are relative to it
    cleared: clearance.Clearance
    context: dict[str, str]  # what the report says about where the clips came from
    accents: dict[str, str] | None = None  # per speaker; None: the one accent (`--accent` or the pack's)
    refusal: Refusal | None = None  # why a selection may not back a verdict
    sets: dict[str, int] = field(init=False)

    def __post_init__(self) -> None:
        names = dict.fromkeys(c.set for c in self.clips)
        object.__setattr__(self, "sets", {name: sum(c.set == name for c in self.clips) for name in names})


def eval_input(args: argparse.Namespace, register: Mapping[str, str]) -> EvalInput:
    return manifest_input(args, register) if args.manifest else selection_input(args, register)


def manifest_input(args: argparse.Namespace, register: Mapping[str, str]) -> EvalInput:
    path = Path(args.manifest)
    clips = manifest.load(path, register=register)
    if args.speaker:
        clips = [c for c in clips if c.speaker in args.speaker]
        if not clips:
            raise NoClipsError(f"no clips for speaker(s) {', '.join(args.speaker)}")
    cleared = clearance.assess(clips, register, allow_synthetic=args.allow_synthetic)
    context = {"manifest": str(args.manifest), "accent": args.accent or "the pack's base accent"}
    return EvalInput(clips, path.parent, cleared, context)


def selection_input(args: argparse.Namespace, register: Mapping[str, str]) -> EvalInput:
    data = root_from(args)
    selection = selection_from(args.select, data, args.pack, default_splits=None, speakers=args.speaker)
    cleared, refusal = gate_clearance(selection, register, allow_synthetic=args.allow_synthetic)
    accents = selection.accents(args.accent)
    context = {
        "selection": " ".join(f"--select {s.text}" for s in args.select),
        "data root": str(data),
        "corpora": describe(selection),
        "accent": args.accent or f"each speaker's, from the corpus registry ({accent_summary(accents)})",
    }
    if refusal is not None:
        context["not a gate, because"] = "; ".join(refusal.problems)
    return EvalInput(selection.grading_clips(), selection.audio_root, cleared, context, accents, refusal)
