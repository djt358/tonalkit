"""Writing a synthetic corpus: the WAVs under `wav/`, `manifest.jsonl` and `truth.jsonl` (the f0
ground truth, one `{"id", "f0_hz"}` per row; `null` where unvoiced)."""

from __future__ import annotations

import json
import math
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


def _positive_finite(x: object) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def read_truth(out_dir: str | Path) -> dict[str, list[float | None]]:
    """The f0 truth `write_index` wrote: clip id to Hz per 10 ms frame (None where unvoiced), in
    file order. Raises `SynthError` naming the file and line for a line that is not
    `{"id", "f0_hz"}`, has a frame that is not null or a positive finite number, or repeats an
    id, and if `out_dir` has no `truth.jsonl`."""
    path = Path(out_dir) / "truth.jsonl"
    if not path.is_file():
        raise SynthError(f"no truth.jsonl in {out_dir}")
    truth: dict[str, list[float | None]] = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path}:{lineno}"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise SynthError(f"{where}: invalid JSON: {e}") from e
        if not (
            isinstance(obj, dict)
            and isinstance(obj.get("id"), str)
            and isinstance(obj.get("f0_hz"), list)
        ):
            raise SynthError(f"{where}: expected an id and f0_hz")
        for i, hz in enumerate(obj["f0_hz"]):
            if hz is not None and not _positive_finite(hz):
                raise SynthError(
                    f"{where}: f0_hz[{i}] is {hz!r}, expected null or a positive finite number"
                )
        if obj["id"] in truth:
            raise SynthError(f"{where}: duplicate id {obj['id']!r}")
        truth[obj["id"]] = obj["f0_hz"]
    return truth


def write_corpus(out_dir: str | Path, made: Sequence[Made]) -> None:
    """Write perturbed clips (WAVs under `wav/`, the manifest and the truth) to `out_dir`."""
    for audio, _, clip in made:
        write_wav(out_dir, clip, audio)
    write_index(out_dir, [c for _, _, c in made], [f0 for _, f0, _ in made])
