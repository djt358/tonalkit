"""Kit bundles for the intake and purge tests: the session the kit would export for some cards of
the real deck (kit/deck/s05-v1.json, so the deck lookup finds it by hash), as a zip or an unzipped
folder. The clips are synthetic: a constant level of -40 dBFS by default (`levels` sets a card's
own constant sample value, 0 for digital silence), or (`voiced=True`) the harmonic test voice of
support.py saying each card's produced tones. No recording of anyone."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
from bundle_support import make_bundle, session_dict, wav_bytes
from scipy.io import wavfile
from support import RATE, utterance

from tonekit_harness import clearance, cli
from tonekit_harness.intake.run import IntakeOptions
from tonekit_harness.repo import repo_root

DECK_ID = "s05-v1"
DECK_JSON = repo_root() / "kit" / "deck" / f"{DECK_ID}.json"
CARDS = {c["id"]: c for c in json.loads(DECK_JSON.read_text(encoding="utf-8"))["card"]}
# two whole gate pairs, a register card and a minimal-set member
SMALL = ["g01-c", "g01-e", "g02-c", "g02-e", "r01", "m01-a"]
AUDIBLE = 328  # a constant clip at -40 dBFS: well over intake's silence line (-60 dBFS)


def deck_sha() -> str:
    return hashlib.sha256(DECK_JSON.read_bytes()).hexdigest()


def pcm16(x: np.ndarray) -> bytes:
    """16 kHz mono 16-bit PCM WAV bytes of float samples in [-1, 1], as the kit writes them."""
    buf = io.BytesIO()
    wavfile.write(buf, RATE, np.round(np.clip(x, -1.0, 1.0) * 32767).astype(np.int16))
    return buf.getvalue()


def card_wav(card: str, *, voiced: bool, seed: int = 0, level: int | None = None) -> bytes:
    """The clip of `card`: a constant `level` if one is given, else the default constant or the test voice."""
    if level is not None:
        return wav_bytes(level=level)
    if not voiced:
        return wav_bytes(level=AUDIBLE)
    return pcm16(utterance(CARDS[card]["produced_tones"], seed))


def kit_session(code: str = "K7Q2MD", cards: list[str] | None = None, skipped: list[str] | None = None,
                **overrides) -> dict:  # fmt: skip
    cards = SMALL if cards is None else cards
    clips = [
        {"card": c, "file": f"clips/{c}.wav", "takes": 1 + i % 3, "duration_s": 1.0, "peak": 0.5}
        for i, c in enumerate(cards)
    ]
    return session_dict(
        deck={"id": DECK_ID, "sha256": deck_sha()},
        session=code,
        clips=clips,
        skipped=list(skipped or []),
        **overrides,
    )


def kit_bundle(
    where: Path,
    code: str = "K7Q2MD",
    cards: list[str] | None = None,
    skipped: list[str] | None = None,
    *,
    folder: bool = False,
    voiced: bool = False,
    session: dict | None = None,
    levels: dict[str, int] | None = None,
) -> Path:
    """`where/tonekit-s05-v1-<code>.zip`, or with `folder` the folder it unzips to. `levels` gives
    some cards a constant clip of that sample value instead (0: digital silence)."""
    session = session or kit_session(code, cards, skipped)
    levels = levels or {}
    wavs = {
        c["file"]: card_wav(c["card"], voiced=voiced, seed=i, level=levels.get(c["card"]))
        for i, c in enumerate(session["clips"])
    }
    where.mkdir(parents=True, exist_ok=True)
    name = f"tonekit-{DECK_ID}-{code}"
    if not folder:
        return make_bundle(where / f"{name}.zip", session, wavs)
    out = where / name
    (out / "clips").mkdir(parents=True)
    (out / "session.json").write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
    for member, data in wavs.items():
        (out / member).write_bytes(data)
    return out


def tkh(capsys, *argv: str) -> tuple[int, str, str]:
    """`tkh ARGV...`: the exit code, what it printed and what it complained about."""
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def tree(root: Path) -> dict[str, bytes]:
    """Every file under `root` by relative path, with its bytes."""
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def entries(root: Path) -> list[str]:
    """Every file and directory under `root` (relative paths): an empty directory left behind shows."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) if root.exists() else []


def options(root: Path, **kw) -> IntakeOptions:
    """Intake options for the data root `root`, the repository's decks and packs, and its register."""
    return IntakeOptions(root=root, repo=repo_root(), register=clearance.read_register(None), **kw)
