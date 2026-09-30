"""Writing a synthetic corpus: the WAVs under `wav/`, `manifest.jsonl` and `truth.jsonl` (the f0
ground truth, one `{"id", "f0_hz"}` per row; `null` where unvoiced)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from . import manifest
from .family import SynthError
from .ingest import TARGET_SR
from .manifest import Clip

# One perturbed clip: its samples, the f0 truth per 10 ms frame (None where unvoiced), its row.
Made = tuple[np.ndarray, list[float | None], Clip]


def require_empty(out_dir: str | Path) -> None:
    """Refuse an `out_dir` that already holds anything, so a new manifest can never sit beside
    stale WAVs (or a stale manifest beside new ones). A directory that does not exist yet, or is
    empty, is fine."""
    out = Path(out_dir)
    if out.is_dir() and any(out.iterdir()):
        raise SynthError(
            f"{out} is not empty; refusing to mix new clips with what is there "
            "(choose another --out, or empty it)"
        )


def write_wav(out_dir: str | Path, clip: Clip, audio: np.ndarray) -> None:
    """Write `audio` to `clip.path` under `out_dir` as a 16 kHz mono float32 WAV."""
    path = Path(out_dir) / clip.path
    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(path, TARGET_SR, np.asarray(audio, dtype=np.float32))


def write_index(out_dir: str | Path, clips: Sequence[Clip], truths: Sequence[list[float | None]]):
    """Write `manifest.jsonl` and `truth.jsonl` (`{"id", "f0_hz"}` per clip, null if unvoiced)."""
    out = Path(out_dir)
    manifest.write(out / "manifest.jsonl", list(clips))
    lines = (
        json.dumps({"id": c.id, "f0_hz": f0}) + "\n" for c, f0 in zip(clips, truths, strict=True)
    )
    (out / "truth.jsonl").write_text("".join(lines), encoding="utf-8")


def write_corpus(out_dir: str | Path, made: Sequence[Made]) -> None:
    """Write perturbed clips (WAVs under `wav/`, the manifest and the truth) to `out_dir`."""
    for audio, _, clip in made:
        write_wav(out_dir, clip, audio)
    write_index(out_dir, [c for _, _, c in made], [f0 for _, f0, _ in made])
