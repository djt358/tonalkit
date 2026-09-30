"""Whether a run's clips may back the S1 gate verdict (spec §9, §13).

The gate is measured on real recordings only. A clip counts towards a verdict when it is not
synthetic and its `source` is `allow` in data-register.csv (the `shipped_weights_training` column,
which `tkh provenance` reads for datasets as well). Anything else makes the run "NOT A GATE", or
"SMOKE (synthetic)" when every such clip is synthetic and the caller said smoke runs are intended.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import provenance
from .manifest import Clip, ManifestError

SYNTHETIC_SOURCE = "synthetic-world"  # the register id of resynthesised audio


def default_register() -> Path:
    """data-register.csv at the root of the checkout this harness lives in."""
    return Path(__file__).resolve().parents[3] / "data-register.csv"


def read_register(path: str | None) -> dict[str, str]:
    """The register named by `--register`, or the checkout's own, as {id: shipped_weights_training}.
    Raises `OSError` if it is not there and `provenance.ProvenanceError` if it is unusable."""
    if path is None:
        path = str(default_register())
        if not Path(path).is_file():
            raise FileNotFoundError(f"{path}: no data register next to the harness; pass --register")
    return provenance.load_register(Path(path))


@dataclass(frozen=True)
class Clearance:
    """What a run may claim: `gate` (a real corpus: issue the verdict), `smoke` (synthetic clips,
    asked for: no verdict) or `not a gate` (synthetic or not-allowed clips: no verdict).
    `uncleared` counts the clips that are synthetic or whose source is not allowed."""

    mode: Literal["gate", "smoke", "not a gate"]
    uncleared: int = 0

    @property
    def verdict(self) -> bool:
        """Whether the S1 verdict (PASS or FAIL) may be issued."""
        return self.mode == "gate"

    @property
    def label(self) -> str | None:
        """The headline that stands in for PASS/FAIL; None when a verdict may be issued."""
        if self.mode == "smoke":
            return "SMOKE (synthetic)"
        if self.mode == "not a gate":
            return f"NOT A GATE ({self.uncleared} synthetic / non-allowed clips)"
        return None

    @property
    def reason(self) -> str | None:
        """Why there is no verdict; None when one may be issued."""
        if self.mode == "smoke":
            return (
                "every clip that is not a real recording is synthetic and `--allow-synthetic` was "
                "given: a smoke run that checks the plumbing"
            )
        if self.mode == "not a gate":
            return "some clips are synthetic or come from a source the data register does not allow"
        return None


def is_synthetic(clip: Clip) -> bool:
    """Synthetic audio: the `synthetic-world` source, a `synthetic` field or the synthetic set."""
    return clip.source == SYNTHETIC_SOURCE or clip.synthetic is not None or clip.set == "synthetic"


def is_allowed(clip: Clip, register: Mapping[str, str]) -> bool:
    """Whether the register says `allow` for the clip's source (unknown sources are not allowed)."""
    return register.get(clip.source) == "allow"


def assess(
    clips: Iterable[Clip], register: Mapping[str, str], *, allow_synthetic: bool = False
) -> Clearance:
    """The clearance of a run over `clips`, whatever their set: a synthetic register clip would
    teach a speaker's register to the gate clips just as a recording would.

    Raises `ManifestError` if the manifest mixes clips of the synthetic set with gate clips: a
    gate corpus holds recordings, and synthetic clips are graded from a manifest of their own."""
    clips = list(clips)
    in_set = sum(c.set == "synthetic" for c in clips)
    if in_set and any(c.set == "gate" for c in clips):
        s = "" if in_set == 1 else "s"
        raise ManifestError(
            f"{in_set} synthetic clip{s} (set 'synthetic') mixed with gate clips; "
            "grade synthetic clips from a manifest of their own"
        )
    synthetic = [c for c in clips if is_synthetic(c)]
    other = [c for c in clips if not is_synthetic(c) and not is_allowed(c, register)]
    uncleared = len(synthetic) + len(other)  # a clip is in only one of the two
    if not uncleared:
        return Clearance("gate")
    smoke = allow_synthetic and not other
    return Clearance("smoke" if smoke else "not a gate", uncleared)
