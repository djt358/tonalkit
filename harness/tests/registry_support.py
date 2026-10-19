"""Tmp data roots for the registry tests. Manifests are rows only (no audio) unless a test writes
some with `support.make_clip`; nothing here is a recording or real speaker metadata."""

from __future__ import annotations

import json
from pathlib import Path

from support import candidate

from tonekit_harness.contracts.registry import hashed_split
from tonekit_harness.manifest import Clip, Condition

# What the tests treat as the data register: the checkout's real ids for the datasets, and the
# volunteer corpus's row that P2 adds (the checkout's register does not have it yet).
REGISTER = {
    "volunteer-corpus": "allow",
    "dj-corpus": "allow",
    "aishell-3": "allow",
    "latic": "verify",
    "magicdata-read": "deny",
    "synthetic-world": "deny",
}

# Their splits are the pinned hashed ones (test_registry.GOLDEN_SPLITS): a public or synthetic
# corpus must store a speaker's hash split (R82).
CALIB, DEV, HELDOUT = "SSB0001", "SSB0002", "SSB0004"
SYNTHETIC_CALIB = "s2"  # hashed_split("s2") == "calib"


def ids_in_split(split: str, n: int, prefix: str = "h") -> list[str]:
    """The first `n` ids `<prefix><i>` whose hash split is `split`, for public corpora of many
    speakers."""
    out, i = [], 0
    while len(out) < n:
        if hashed_split(f"{prefix}{i}") == split:
            out.append(f"{prefix}{i}")
        i += 1
    return out


def speaker(speaker_id: str, split: str = "gate", accent: str | None = None, **extra) -> dict:
    """A `[[speaker]]`; with no `accent` it is graded against the default for its
    `grew_up_hearing` (R82)."""
    return {"id": speaker_id, "accent": accent, "split": split} | extra


def volunteer(code: str, hearing: str, split: str = "gate") -> dict:
    """A volunteer as intake writes one: no stored accent (R82)."""
    return speaker(f"v-{code.lower()}", split, background="native", grew_up_hearing=hearing, sessions=[code])


def clip(
    clip_id: str,
    speaker_id: str,
    *,
    source: str,
    set: str = "gate",
    label: str = "correct",
    pair: str | None = None,
    path: str | None = None,
) -> Clip:
    return Clip(
        id=clip_id,
        path=path or f"audio/{speaker_id}/{clip_id}.wav",
        speaker=speaker_id,
        set=set,  # type: ignore[arg-type]
        pair=pair,
        label=label,  # type: ignore[arg-type]
        intended=candidate(["4", "1", "3"]),
        condition=Condition(noise="none", distance="synthetic"),
        source=source,
        synthetic={"generator": "tests/registry_support.py"} if set == "synthetic" else None,
    )


def toml_table(header: str, values: dict) -> str:
    """A TOML table: JSON strings and arrays are TOML strings and arrays."""
    return f"[{header}]\n" + "".join(f"{k} = {json.dumps(v)}\n" for k, v in values.items() if v is not None)


def write_corpus_file(
    directory: Path, corpus_id: str, *, kind: str, source: str, speakers: list[dict], lect: str = "cmn",
    manifest: str = "manifest.jsonl",
) -> Path:  # fmt: skip
    meta = {"id": corpus_id, "source": source, "kind": kind, "lect": lect, "manifest": manifest}
    text = toml_table("corpus", meta) + "".join("\n" + toml_table("[speaker]", s) for s in speakers)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "corpus.toml"
    path.write_text(text, encoding="utf-8")
    return path


def add_corpus(
    root: Path,
    corpus_id: str,
    *,
    kind: str,
    source: str,
    speakers: list[dict],
    clips: list[Clip] | None = None,
    **kw,
) -> Path:
    """`<root>/corpora/<corpus_id>` with a corpus.toml and (if `clips` is not None) a manifest.
    Returns the corpus directory."""
    directory = root / "corpora" / corpus_id
    write_corpus_file(directory, corpus_id, kind=kind, source=source, speakers=speakers, **kw)
    if clips is not None:
        manifest = directory / kw.get("manifest", "manifest.jsonl")
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("".join(c.model_dump_json() + "\n" for c in clips), encoding="utf-8")
    return directory


def speaker_clips(speaker_id: str, source: str, *, n: int = 2, set: str = "gate") -> list[Clip]:
    """`n` clips of one speaker, ids `<speaker>-<set>-<i>`."""
    return [clip(f"{speaker_id}-{set}-{i}", speaker_id, source=source, set=set) for i in range(n)]


def build_composed_root(root: Path) -> Path:
    """A data root with the four kinds of corpus the registry composes:

    - `volunteers-2026-10` (recorded, volunteer-corpus): two gate speakers, 2 gate + 1 register clips each
    - `dj-2026-10` (recorded, dj-corpus): one gate speaker `dj` (stored accent cmn-TW), 2 gate clips
    - `aishell3` (public, aishell-3): calib, dev and heldout speakers, 2 gate clips each
    - `smoke` (synthetic, synthetic-world): one calib speaker `s2`, 2 synthetic clips

    The volunteers store no accent (taiwan and mainland: cmn-TW and cmn-standard by default).
    """
    v = "volunteer-corpus"
    add_corpus(
        root, "volunteers-2026-10", kind="recorded", source=v,
        speakers=[volunteer("K7Q2MD", "taiwan"), volunteer("ABCDE2", "mainland")],
        clips=[
            c for s in ("v-k7q2md", "v-abcde2")
            for c in speaker_clips(s, v) + speaker_clips(s, v, n=1, set="register")
        ],
    )  # fmt: skip
    add_corpus(
        root, "dj-2026-10", kind="recorded", source="dj-corpus",
        speakers=[speaker("dj", "gate", "cmn-TW")], clips=speaker_clips("dj", "dj-corpus"),
    )  # fmt: skip
    add_corpus(
        root, "aishell3", kind="public", source="aishell-3",
        speakers=[speaker(CALIB, "calib"), speaker(DEV, "dev"), speaker(HELDOUT, "heldout")],
        clips=[c for s in (CALIB, DEV, HELDOUT) for c in speaker_clips(s, "aishell-3")],
    )  # fmt: skip
    add_corpus(
        root, "smoke", kind="synthetic", source="synthetic-world",
        speakers=[speaker(SYNTHETIC_CALIB, "calib")],
        clips=speaker_clips(SYNTHETIC_CALIB, "synthetic-world", set="synthetic"),
    )  # fmt: skip
    return root
