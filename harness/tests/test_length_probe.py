"""The length probe behind R123 (harness/scripts/length_probe.py) still runs: two short spaced
phrases of the synthetic voice, in the index format tonekit-testkit's probe_phrases example
writes, graded by `tkh eval`'s and `tkh fit`'s code paths."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from support import EDGE_S, GAP_S, SYLLABLE_S, make_clip

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "length_probe.py"
FRAME_S = 0.01


def load_probe():
    spec = importlib.util.spec_from_file_location("length_probe", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up while it loads
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def frames(n: int) -> str:
    """Each syllable's true `start:end` frames, as support.utterance spaces them."""
    starts = [EDGE_S + k * (SYLLABLE_S + GAP_S) for k in range(n)]
    return " ".join(f"{round(s / FRAME_S)}:{round((s + SYLLABLE_S) / FRAME_S)}" for s in starts)


def test_the_length_probe_grades_phrases_per_length_and_declination(tmp_path):
    lines = []
    for cid, tones in (("len03-a-0-decl0", ["4", "1", "3"]), ("len04-a-0-decl0", ["1", "2", "4", "1"])):
        make_clip(tmp_path, cid, tones, set="sentence", speaker="a")
        lines.append(f"{cid}\ta\t0\t{' '.join(tones)}\t{frames(len(tones))}")
    (tmp_path / "phrases.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    probe = load_probe()
    tallies = probe.probe(tmp_path, tmp_path / "cache")
    assert sorted(tallies) == [(3, 0.0), (4, 0.0)]
    for (n, _), t in tallies.items():
        assert (t.clips, t.syllables) == (1, n)
        assert t.placed == n  # the forced decode puts every syllable on its own
    table = probe.table(tallies)
    assert table.splitlines()[2].startswith("| 3 | 0 | 1 |")
