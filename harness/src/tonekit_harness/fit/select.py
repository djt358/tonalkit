"""Which clips a fit may read: only those of speakers whose corpus split is `calib`."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..contracts.registry import load_corpus_file
from ..manifest import Clip


class FitError(ValueError):
    """A fit was asked to read what it may not, or has nothing to read."""


def calib_speakers(corpus_toml: str | Path, pack: str | Path | None = None) -> list[str]:
    """The speakers of the corpus whose split is `calib`, in file order."""
    corpus = load_corpus_file(corpus_toml, pack=pack)
    return [s.id for s in corpus.speaker if s.split == "calib"]


def fit_clips(clips: Sequence[Clip], allowed: Sequence[str], wanted: Sequence[str] | None) -> list[Clip]:
    """The clips of `wanted` speakers (default: every `allowed` one). A wanted speaker who is not
    in `allowed` (the corpus's calib speakers) is refused: gate and held-out speakers are never
    fitted on (R72)."""
    if not wanted and not allowed:
        raise FitError("no speaker of the corpus is in the calib split; nothing may be fitted on")
    chosen = list(wanted) if wanted else list(allowed)
    refused = [s for s in chosen if s not in allowed]
    if refused:
        raise FitError(f"speaker(s) {', '.join(refused)} are not in the calib split; only calib speakers are fitted on")
    out = [c for c in clips if c.speaker in chosen]
    if not out:
        raise FitError(f"no clips for speaker(s) {', '.join(chosen) or '(none)'}")
    return out
