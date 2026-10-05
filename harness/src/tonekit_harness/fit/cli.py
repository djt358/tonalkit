"""`tkh fit`: fit the calibration (and, with `--templates`, the pack's tone templates) on the
calibration speakers of one corpus, and write the fitted files."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from .. import calibration, clearance, manifest
from ..evaluate import EvalError, Grader, _chain_registers, base_accent
from .observe import Observation, observe_clip
from .select import FitError, calib_speakers, fit_clips
from .unpitched import fit_unpitched


def pack_tones(pack_toml: str) -> list[str]:
    return [t["id"] for t in tomllib.loads(pack_toml).get("tone", [])]


def observations(clips, pack_toml: str, calib_json: str | None, root: Path) -> list[Observation]:
    """Every syllable of `clips` observed on the given pack and calibration (registers chained
    from each speaker's register clips, as `tkh eval` grades)."""
    grader = Grader(pack_toml, calib_json, base_accent(pack_toml), root, None)
    registers, _ = _chain_registers(clips, grader)
    return [o for c in clips for o in observe_clip(c, grader, registers[c.speaker])]


def fit_calibration(clips, pack_toml: str, calib_json: str, root: Path, rounds: int) -> dict:
    """The calibration with its `unpitched` section fitted on `clips`, refitted `rounds` times
    (each round observes with the previous round's evidence, which moves where the decoder puts
    unpitched syllables)."""
    calib = json.loads(calib_json)
    tones = pack_tones(pack_toml)
    for _ in range(rounds):
        obs = observations(clips, pack_toml, json.dumps(calib), root)
        calib["unpitched"] = fit_unpitched(obs, tones)
    return calib


def _run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    corpus_toml = Path(args.corpus) if args.corpus else manifest_path.parent / "corpus.toml"
    try:
        clips = manifest.load(manifest_path, register=clearance.read_register(args.register))
        chosen = fit_clips(clips, calib_speakers(corpus_toml, args.pack), args.speaker)
        files = calibration.load(args.pack, args.calib)
        calib = fit_calibration(
            chosen,
            files.pack_toml,
            files.calib_json or json.dumps(DEFAULT_CALIB),
            manifest_path.parent,
            args.rounds,
        )
    except (FitError, EvalError, manifest.ManifestError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out = Path(args.out_calib)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(calib, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    speakers = sorted({c.speaker for c in chosen})
    print(f"fitted on {len(chosen)} clips of {', '.join(speakers)}; wrote {out}")
    return 0


# The seed calibration (packs/cmn/cmn.calib.json as first shipped), for a pack without one.
DEFAULT_CALIB = {
    "temperature": 1.0,
    "fusion": {"beta0": 0.0, "beta_acoustic": 1.0, "beta_transcript": 0.5, "beta_neural": 0.0, "veto_cap": 0.05},
    "decode": {
        "filler_per_frame": 0.03,
        "unvoiced_syllable_llr": -3.0,
        "insertion_llr": -2.0,
        "null_bias": -2.0,
        "dur_sigma": 0.4,
        "default_rate_s": 0.22,
    },
}


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "fit",
        help="fit the calibration on a corpus's calib-split speakers and write it (rulings R103, R106)",
    )
    p.add_argument("--manifest", required=True, help="corpus manifest (JSONL)")
    p.add_argument("--corpus", help="the corpus's corpus.toml (default: beside the manifest); it says which speakers are calib")
    p.add_argument("--pack", required=True, help="language pack TOML (e.g. packs/cmn/cmn.toml)")
    p.add_argument("--calib", help="calibration JSON to start from (default: the one beside the pack)")
    p.add_argument("--speaker", action="append", help="fit on this calib speaker only (repeatable; default: every calib speaker)")
    p.add_argument("--out-calib", required=True, help="where to write the fitted calibration JSON")
    p.add_argument("--rounds", type=int, default=2, help="fit rounds (default 2)")
    p.add_argument("--register", help="data register (default: data-register.csv at the repository root)")
    p.set_defaults(func=_run)
