"""The length probe behind `tkh adapt --max-syllables` (ruling R123): how `tkh fit`'s forced decode
(`fit.observe`) and `tkh eval` cope with sentence-length clips.

Public corpora are read sentences of 5 to 47 syllables. This grades fluent synthetic phrases of
4 to 48 syllables (tonekit-testkit's `synth_fluent`, four voices, six phrases each per length,
each level and with one Chao step of declination) as `sentence` clips, the way
`tkh eval --register-from speaker` and `tkh fit` read them, and prints, per length and
declination:

- eval: the share of clips scored, the share of syllables heard as the spoken tone, and the time
  to analyse and to assess a clip;
- fit: the share of syllables the forced decode measured as a shape, the share it placed on the
  true syllable (the decoded span's midpoint inside the syllable's true frames), the share of
  clips with one nucleus per syllable (`clean`), and the time of the forced decode.

From harness/:

    cargo run -p tonekit-testkit --example probe_phrases --release -- /tmp/probe
    uv run python scripts/length_probe.py /tmp/probe

Synthetic audio only; nothing is written but the WAVs the example makes.
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from tonekit_harness import evaluate
from tonekit_harness.fit.observe import SHAPE, observe_clip
from tonekit_harness.manifest import Candidate, Clip, Condition
from tonekit_harness.repo import repo_root


@dataclass
class Phrase:
    clip: Clip
    declination: float
    frames: list[tuple[int, int]]


@dataclass
class Tally:
    clips: int = 0
    scored: int = 0
    syllables: int = 0
    heard_right: int = 0
    shapes: int = 0
    placed: int = 0
    clean: int = 0
    analyse_s: list[float] = field(default_factory=list)
    assess_s: list[float] = field(default_factory=list)
    decode_s: list[float] = field(default_factory=list)


def phrases(directory: Path) -> list[Phrase]:
    out = []
    for line in (directory / "phrases.tsv").read_text(encoding="utf-8").splitlines():
        cid, speaker, declination, tones, frames = line.split("\t")
        spoken = tones.split()
        clip = Clip(
            id=cid,
            path=f"{cid}.wav",
            speaker=speaker,
            set="sentence",
            label="correct",
            intended=Candidate(id=cid, tones=spoken, labels=[]),
            produced_tones=spoken,
            condition=Condition(noise="none", distance="synthetic"),
            source="synthetic-world",
            context="phrase",
        )
        spans = [tuple(int(x) for x in f.split(":")) for f in frames.split()]
        out.append(Phrase(clip, float(declination), spans))  # type: ignore[arg-type]
    return out


def _inside(span: tuple[int, int] | None, truth: tuple[int, int]) -> bool:
    if span is None:
        return False
    middle = (span[0] + span[1]) / 2
    return truth[0] <= middle < truth[1]


def probe(directory: Path, cache: Path) -> dict[tuple[int, float], Tally]:
    """Per (syllables, declination), what eval and the forced decode made of the phrases. The
    analysis is timed once and cached, so the forced decode's time is its own."""
    repo = repo_root()
    pack = (repo / "packs" / "cmn" / "cmn.toml").read_text(encoding="utf-8")
    calib = (repo / "packs" / "cmn" / "cmn.calib.json").read_text(encoding="utf-8")
    found = phrases(directory)
    grader = evaluate.Grader(pack, calib, evaluate.base_accent(pack), directory, cache)
    clips = [p.clip for p in found]
    registers, _ = evaluate.clip_registers(clips, grader, "speaker")
    tallies: dict[tuple[int, float], Tally] = defaultdict(Tally)
    for p in found:
        t = tallies[(len(p.frames), p.declination)]
        register = registers[p.clip.id]
        start = time.perf_counter()
        analysis = grader.analysis(p.clip, register)
        t.analyse_s.append(time.perf_counter() - start)
        start = time.perf_counter()
        result, _ = grader.assess(p.clip, analysis)
        t.assess_s.append(time.perf_counter() - start)
        start = time.perf_counter()
        observed = observe_clip(p.clip, grader, register)  # its analysis is now in the cache
        t.decode_s.append(time.perf_counter() - start)
        t.clips += 1
        t.scored += result.overall is not None
        t.syllables += len(p.frames)
        t.heard_right += sum(s.heard == s.expected for s in result.syllables)
        t.shapes += sum(o.kind == SHAPE for o in observed)
        t.placed += sum(_inside(o.span, truth) for o, truth in zip(observed, p.frames, strict=True))
        t.clean += observed[0].clean if observed else False
    return dict(sorted(tallies.items()))


def _share(n: int, d: int) -> str:
    return f"{n / d:.2f}" if d else "n/a"


def _ms(xs: list[float]) -> str:
    return f"{1000 * statistics.median(xs):.0f}/{1000 * max(xs):.0f}"


def table(tallies: dict[tuple[int, float], Tally]) -> str:
    header = (
        "| syllables | declination | clips | eval: scored | eval: heard as spoken | fit: shape "
        "| fit: on the true syllable | fit: clean clips | analyse ms (median/max) | assess ms "
        "| forced decode ms |"
    )
    lines = [header, "|" + "---|" * 11]
    for (n, declination), t in tallies.items():
        lines.append(
            f"| {n} | {declination:g} | {t.clips} | {_share(t.scored, t.clips)} "
            f"| {_share(t.heard_right, t.syllables)} "
            f"| {_share(t.shapes, t.syllables)} | {_share(t.placed, t.syllables)} | {_share(t.clean, t.clips)} "
            f"| {_ms(t.analyse_s)} | {_ms(t.assess_s)} | {_ms(t.decode_s)} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dir", type=Path, help="the directory probe_phrases wrote")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as cache:
        print(table(probe(args.dir, Path(cache))))


if __name__ == "__main__":
    main()
