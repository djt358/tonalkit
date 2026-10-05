#!/usr/bin/env python3
"""Checks a kit session bundle against docs/s05/contracts.md §2.

    python3 kit/tests/check_bundle.py BUNDLE.zip [--deck DECK.json] [--min-duration 0.3]

Exits 1 listing every problem found. The contract is C0's model: when
`tonekit_harness.contracts.bundle` can be imported (the harness env, or harness/src with pydantic
installed), its `read_bundle` validates the bundle. Otherwise a thin stdlib fallback checks the
same shape (plus kit/schema/ via `jsonschema` when both are there). Either way, the kit's own
checks follow: the zip's name, the timestamps' order, each clip's length and peak against its WAV,
and, with --deck, the deck's hash and card ids.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

SCHEMA = "tonekit.session.v1"
CODE = re.compile(r"^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}$")
CARD_ID = re.compile(r"^[a-z0-9-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ENUMS = {
    "background": {"native", "heritage", "learner", "prefer_not"},
    "grew_up_hearing": {
        "mainland",
        "taiwan",
        "singapore_malaysia",
        "hong_kong_macau",
        "other",
        "prefer_not",
    },
    "reading": {"hanzi", "hanzi+pinyin"},
    "script": {"simplified", "traditional"},
}
# R83: always all three, each true, false or null (null: the browser didn't report it).
CONSTRAINT_KEYS = {"echoCancellation", "noiseSuppression", "autoGainControl"}
TOP_KEYS = {
    "schema",
    "deck",
    "session",
    "started_at",
    "finished_at",
    "consent",
    "speaker",
    "device",
    "clips",
    "skipped",
}
CLIP_KEYS = {"card", "file", "takes", "duration_s", "peak"}
ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "kit" / "schema"


def wav_info(data: bytes) -> tuple[int, int, int, int, int, float]:
    """(format, channels, rate, bits, frames, peak) of a canonical-or-chunked RIFF/WAVE file."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not RIFF/WAVE")
    fmt = None
    pos = 12
    while pos + 8 <= len(data):
        chunk, size = (
            data[pos : pos + 4],
            struct.unpack("<I", data[pos + 4 : pos + 8])[0],
        )
        body = data[pos + 8 : pos + 8 + size]
        if chunk == b"fmt ":
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif chunk == b"data":
            if fmt is None:
                raise ValueError("data before fmt")
            fmt_tag, channels, rate, _, align, bits = fmt
            frames = len(body) // align
            samples = (
                struct.unpack(f"<{len(body) // 2}h", body[: len(body) // 2 * 2])
                if bits == 16
                else ()
            )
            peak = max((abs(s) for s in samples), default=0) / 32768
            return fmt_tag, channels, rate, bits, frames, peak
        pos += 8 + size + (size & 1)
    raise ValueError("no data chunk")


def check_schema(session: dict, problems: list[str]) -> None:
    candidates = sorted(SCHEMA_DIR.glob("*session*.json")) + sorted(
        SCHEMA_DIR.glob("*bundle*.json")
    )
    if not candidates:
        return
    try:
        import jsonschema
    except ImportError:
        print(
            f"note: {candidates[0].name} present but jsonschema isn't installed; skipped",
            file=sys.stderr,
        )
        return
    for error in jsonschema.Draft202012Validator(
        json.loads(candidates[0].read_text())
    ).iter_errors(session):
        problems.append(
            f"schema {candidates[0].name}: {error.json_path}: {error.message}"
        )


def harness_reader() -> tuple[Callable, type[Exception]] | None:
    """C0's `read_bundle` and `BundleError`: from the environment, else from harness/src."""
    for attempt in range(2):
        try:
            from tonekit_harness.contracts.bundle import BundleError, read_bundle
        except ImportError:
            if attempt:
                return None
            for name in [
                m for m in sys.modules if m.split(".")[0] == "tonekit_harness"
            ]:
                del sys.modules[name]
            sys.path.insert(0, str(ROOT / "harness" / "src"))
            continue
        return read_bundle, BundleError
    return None


def harness_problems(path: Path, reader: tuple[Callable, type[Exception]]) -> list[str]:
    read_bundle, bundle_error = reader
    try:
        read_bundle(path)
    except bundle_error as e:
        lines = str(e).splitlines()
        return [line.strip() for line in lines[1:]] or lines
    return []


def fallback_problems(session: dict, files: dict[str, bytes]) -> list[str]:
    """The contract's shape without the harness (keep in step with C0's model)."""
    problems: list[str] = []
    bad = problems.append
    if set(session) != TOP_KEYS:
        bad(f"session.json keys {sorted(session)} != {sorted(TOP_KEYS)}")
    if session.get("schema") != SCHEMA:
        bad(f"schema {session.get('schema')!r}")
    deck = session.get("deck", {})
    if set(deck) != {"id", "sha256"} or not SHA256.match(str(deck.get("sha256"))):
        bad(f"deck {deck!r}")
    if not CODE.match(str(session.get("session", ""))):
        bad(f"session code {session.get('session')!r}")
    consent = session.get("consent", {})
    if set(consent) != {"version", "agreed_at"} or not consent.get("version"):
        bad(f"consent {consent!r}")

    speaker = session.get("speaker", {})
    if set(speaker) != set(ENUMS):
        bad(f"speaker keys {sorted(speaker)}")
    for key, allowed in ENUMS.items():
        if speaker.get(key) not in allowed:
            bad(f"speaker.{key} {speaker.get(key)!r} not in {sorted(allowed)}")

    device = session.get("device", {})
    if set(device) != {"user_agent", "input_sample_rate", "constraints"}:
        bad(f"device keys {sorted(device)}")
    rate = device.get("input_sample_rate")
    if not isinstance(rate, int) or isinstance(rate, bool) or rate <= 0:
        bad(f"device.input_sample_rate {rate!r}")
    if not isinstance(device.get("user_agent"), str) or not device.get("user_agent"):
        bad("device.user_agent is not a non-empty string")
    constraints = device.get("constraints")
    if (
        not isinstance(constraints, dict)
        or set(constraints) != CONSTRAINT_KEYS
        or not all(v is None or isinstance(v, bool) for v in constraints.values())
    ):
        bad(
            f"device.constraints {constraints!r}: need exactly {sorted(CONSTRAINT_KEYS)}, each bool or null"
        )

    clips = session.get("clips", [])
    skipped = session.get("skipped", [])
    cards = [c.get("card") for c in clips]
    if (
        len(set(cards)) != len(cards)
        or len(set(skipped)) != len(skipped)
        or set(cards) & set(skipped)
    ):
        bad("a card appears twice across clips/skipped")
    for card_id in [*cards, *skipped]:
        if not isinstance(card_id, str) or not CARD_ID.match(card_id):
            bad(f"bad card id {card_id!r}")
    for clip in clips:
        where = f"clip {clip.get('card')}"
        if set(clip) != CLIP_KEYS:
            bad(f"{where}: keys {sorted(clip)}")
            continue
        if clip["file"] != f"clips/{clip['card']}.wav":
            bad(f"{where}: file {clip['file']!r}")
        if not isinstance(clip["takes"], int) or clip["takes"] < 1:
            bad(f"{where}: takes {clip['takes']!r}")
        if not 0 <= clip["peak"] <= 1:
            bad(f"{where}: peak {clip['peak']}")
        data = files.get(clip["file"])
        if data is None:
            bad(f"{where}: {clip['file']} missing from the zip")
            continue
        try:
            fmt_tag, channels, wav_rate, bits, _, _ = wav_info(data)
        except ValueError as e:
            bad(f"{where}: {e}")
            continue
        if (fmt_tag, channels, wav_rate, bits) != (1, 1, 16000, 16):
            bad(
                f"{where}: WAV is format {fmt_tag}, {channels} ch, {wav_rate} Hz, {bits} bit"
            )
    extra = set(files) - {c.get("file") for c in clips}
    if extra:
        bad(f"files in the zip that session.json doesn't list: {sorted(extra)}")
    check_schema(session, problems)
    return problems


def kit_problems(
    path: Path,
    session: dict,
    files: dict[str, bytes],
    deck_path: Path | None,
    min_duration: float,
) -> list[str]:
    """What the kit promises beyond the model's shape."""
    problems: list[str] = []
    bad = problems.append
    deck = session.get("deck", {})
    expected_name = f"tonekit-{deck.get('id')}-{session.get('session')}.zip"
    if path.name != expected_name:
        bad(f"bundle named {path.name}, expected {expected_name}")

    times = {}
    for key, value in [
        ("started_at", session.get("started_at")),
        ("finished_at", session.get("finished_at")),
        ("consent.agreed_at", session.get("consent", {}).get("agreed_at")),
    ]:
        if not TIMESTAMP.match(str(value)):
            bad(f"{key} {value!r} is not YYYY-MM-DDTHH:MM:SSZ")
        else:
            times[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if (
        len(times) == 3
        and not times["started_at"]
        <= times["consent.agreed_at"]
        <= times["finished_at"]
    ):
        bad(f"timestamps out of order: {times}")

    clips = session.get("clips", [])
    for clip in clips:
        where = f"clip {clip.get('card')}"
        duration, peak_said = clip.get("duration_s"), clip.get("peak")
        if not isinstance(duration, (int, float)) or not duration > min_duration:
            bad(f"{where}: duration {duration} s <= {min_duration} s")
            continue
        try:
            _, _, _, _, frames, peak = wav_info(files.get(clip.get("file"), b""))
        except ValueError:
            continue  # reported by the contract check
        if abs(frames / 16000 - duration) > 0.002:
            bad(
                f"{where}: WAV holds {frames / 16000:.3f} s, session.json says {duration}"
            )
        if not isinstance(peak_said, (int, float)) or abs(peak - peak_said) > 0.002:
            bad(f"{where}: WAV peak {peak:.4f}, session.json says {peak_said}")

    if deck_path is not None:
        deck_bytes = deck_path.read_bytes()
        if hashlib.sha256(deck_bytes).hexdigest() != deck.get("sha256"):
            bad(f"deck sha256 doesn't match {deck_path}")
        known = {c["id"] for c in json.loads(deck_bytes)["card"]}
        recorded = {c.get("card") for c in clips} | set(session.get("skipped", []))
        if unknown := recorded - known:
            bad(f"cards not in the deck: {sorted(unknown)}")
    return problems


def check(
    path: Path, deck_path: Path | None, min_duration: float
) -> tuple[list[str], str]:
    """(problems, which contract check ran)."""
    with zipfile.ZipFile(path) as z:
        if (broken := z.testzip()) is not None:
            return [f"CRC error in {broken}"], "zip"
        names = z.namelist()
        if "session.json" not in names:
            return ["no session.json"], "zip"
        session = json.loads(z.read("session.json"))
        files = {n: z.read(n) for n in names if n != "session.json"}
    reader = harness_reader()
    if reader is not None:
        problems, how = harness_problems(path, reader), "tonekit_harness read_bundle"
    else:
        problems, how = (
            fallback_problems(session, files),
            "built-in fallback (harness not importable)",
        )
    return problems + kit_problems(path, session, files, deck_path, min_duration), how


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--deck",
        type=Path,
        help="the deck JSON the kit loaded (checks sha256 and card ids)",
    )
    parser.add_argument("--min-duration", type=float, default=0.3)
    args = parser.parse_args()
    problems, how = check(args.bundle, args.deck, args.min_duration)
    for p in problems:
        print(f"FAIL {args.bundle.name}: {p}", file=sys.stderr)
    if not problems:
        print(f"OK {args.bundle.name} (contract: {how})")
    else:
        print(f"contract check: {how}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
