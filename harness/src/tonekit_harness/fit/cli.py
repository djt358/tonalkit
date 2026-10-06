"""`tkh fit`: fit the calibration (and, with `--templates`, the pack's tone templates) on the
calibration speakers of one corpus, and write the fitted files."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .. import calibration, clearance, manifest
from ..evaluate import REGISTER_FROM, EvalError, Grader, base_accent, clip_registers
from .observe import Observation, observe_clip
from .packfile import fitted_pack, render, seed_expectations
from .select import FitError, calib_speakers, fit_clips
from .tail import fit_creaky_tail
from .templates import fit_spread, fit_templates
from .unpitched import fit_unpitched


def pack_tones(pack_toml: str) -> list[str]:
    return [t["id"] for t in tomllib.loads(pack_toml).get("tone", [])]


def observations(
    clips,
    pack_toml: str,
    calib_json: str | None,
    root: Path,
    cache: Path | None = None,
    register_from: str = "drill",
) -> list[Observation]:
    """Every syllable of `clips` observed on the given pack and calibration, each clip analysed
    with the register `tkh eval --register-from` gives it. Analyses are cached in `cache`."""
    grader = Grader(pack_toml, calib_json, base_accent(pack_toml), root, cache)
    registers, _ = clip_registers(list(clips), grader, register_from)
    return [o for c in clips for o in observe_clip(c, grader, registers[c.id])]


@dataclass
class Fitted:
    pack_toml: str
    calib: dict


HEADER = """cmn pack, fitted by `tkh fit` (ruling R109) on calibration speakers' recordings: the base
accent's full-tone realisations by place in the phrase (t<tone>-medial, t<tone>-final) and the
tolerance's contour, onset and offset σ. Citations, the neutral tone's rules and the other
accents are the seed's. Provenance: PROVENANCE.toml."""


def fit(
    clips,
    seed_pack: str,
    seed_calib: str,
    root: Path,
    rounds: int,
    templates: bool,
    register_from: str = "drill",
    shrink: float = 0.0,
) -> Fitted:
    """Fits `rounds` times on `clips`: with `templates`, the pack's templates and spreads (on the
    observations of the files fitted so far), then the calibration's unpitched and creaky-tail
    evidence (on the observations of the newly fitted pack). Each round observes with the previous round's files,
    which moves where the decoder puts syllables. Templates are shrunk towards the seed pack's
    expectations with strength `shrink` (`fit_templates`)."""
    pack_toml, calib = seed_pack, json.loads(seed_calib)
    prior = seed_expectations(seed_pack)
    with tempfile.TemporaryDirectory() as cache:
        for _ in range(rounds):
            if templates:
                obs = observations(clips, pack_toml, json.dumps(calib), root, Path(cache), register_from)
                fitted = fit_templates(obs, prior, shrink)
                pack_toml = render(fitted_pack(seed_pack, fitted, fit_spread(obs, fitted)), HEADER)
            obs = observations(clips, pack_toml, json.dumps(calib), root, Path(cache), register_from)
            calib["unpitched"] = fit_unpitched(obs, pack_tones(pack_toml))
            calib["creaky_tail"] = fit_creaky_tail(obs, pack_tones(pack_toml))
    return Fitted(pack_toml, calib)


def _run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    corpus_toml = Path(args.corpus) if args.corpus else manifest_path.parent / "corpus.toml"
    try:
        clips = manifest.load(manifest_path, register=clearance.read_register(args.register))
        chosen = fit_clips(clips, calib_speakers(corpus_toml, args.pack), args.speaker)
        files = calibration.load(args.pack, args.calib)
        result = fit(
            chosen,
            files.pack_toml,
            files.calib_json or json.dumps(DEFAULT_CALIB),
            manifest_path.parent,
            args.rounds,
            templates=args.out_pack is not None,
            register_from=args.register_from,
            shrink=args.shrink,
        )
    except (FitError, EvalError, manifest.ManifestError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    written = [_write(args.out_calib, json.dumps(result.calib, indent=2, ensure_ascii=False) + "\n")]
    if args.out_pack is not None:
        written.append(_write(args.out_pack, result.pack_toml))
    speakers = sorted({c.speaker for c in chosen})
    print(f"fitted on {len(chosen)} clips of {', '.join(speakers)}; wrote {', '.join(map(str, written))}")
    return 0


def _write(path: str, text: str) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


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
        help="fit the calibration on a corpus's calib-split speakers and write it (rulings R103, R108, R109)",
    )
    p.add_argument("--manifest", required=True, help="corpus manifest (JSONL)")
    p.add_argument("--corpus", help="the corpus's corpus.toml (default: beside the manifest); it says which speakers are calib")
    p.add_argument("--pack", required=True, help="language pack TOML (e.g. packs/cmn/cmn.toml)")
    p.add_argument("--calib", help="calibration JSON to start from (default: the one beside the pack)")
    p.add_argument("--speaker", action="append", help="fit on this calib speaker only (repeatable; default: every calib speaker)")
    p.add_argument("--out-calib", required=True, help="where to write the fitted calibration JSON")
    p.add_argument(
        "--out-pack",
        help="also fit the pack's tone templates and spreads, and write the fitted pack TOML here",
    )
    p.add_argument("--rounds", type=int, default=2, help="fit rounds (default 2)")
    p.add_argument(
        "--shrink",
        type=float,
        default=0.0,
        help="shrink fitted templates towards the seed pack's as if this many syllables had shown "
        "the seed's contour (default 0: the medians alone)",
    )
    p.add_argument(
        "--register-from",
        choices=REGISTER_FROM,
        default="drill",
        help="where each clip's register comes from, as for tkh eval (default: drill)",
    )
    p.add_argument("--register", help="data register (default: data-register.csv at the repository root)")
    p.set_defaults(func=_run)
