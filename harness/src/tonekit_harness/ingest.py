"""Convert recordings to the 16 kHz mono float32 WAV the tonekit pipeline expects."""

from __future__ import annotations

import argparse
import sys
from math import gcd
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly

TARGET_SR = 16_000


def to_float32(data: np.ndarray) -> np.ndarray:
    """Integer PCM to float32 in [-1, 1); float input is only cast."""
    if data.dtype == np.uint8:
        return ((data.astype(np.float32) - 128.0) / 128.0).astype(np.float32)
    if np.issubdtype(data.dtype, np.integer):
        return (data.astype(np.float64) / (float(np.iinfo(data.dtype).max) + 1.0)).astype(np.float32)
    return data.astype(np.float32)


def to_16k_mono(in_path: str | Path, out_path: str | Path) -> None:
    """Read `in_path`, mix down to mono, resample to 16 kHz, write float32 WAV to `out_path`."""
    sr, data = wavfile.read(in_path)
    x = to_float32(data)
    if x.ndim > 1:
        x = x.mean(axis=1, dtype=np.float32)
    if sr != TARGET_SR:
        g = gcd(sr, TARGET_SR)
        x = resample_poly(x.astype(np.float64), TARGET_SR // g, sr // g).astype(np.float32)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(out_path, TARGET_SR, x)


def _run(args: argparse.Namespace) -> int:
    src = Path(args.dir)
    if not src.is_dir():
        print(f"error: {src} is not a directory", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else src.parent / "ingested"
    if out.resolve() == src.resolve():
        print(f"error: --out is the same directory as the input ({src}); refusing to overwrite", file=sys.stderr)
        return 1
    wavs = sorted(p for p in src.iterdir() if p.is_file() and p.suffix.lower() == ".wav")
    if not wavs:
        print(f"error: no .wav files in {src}", file=sys.stderr)
        return 1
    for p in wavs:
        to_16k_mono(p, out / (p.stem + ".wav"))
    print(f"ingested {len(wavs)} file(s) from {src} to {out}")
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("ingest", help="convert every .wav in a directory to 16 kHz mono")
    p.add_argument("dir", help="directory of .wav recordings")
    p.add_argument("--out", help="output directory (default: <dir>/../ingested)")
    p.set_defaults(func=_run)
