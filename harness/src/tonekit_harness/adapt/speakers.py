"""The corpus.toml of an adapted public corpus (docs/s05/contracts.md section 3): kind `public`,
one `[[speaker]]` per speaker with a kept row, in the split its id hashes to (R69, R82), with what
the corpus says about them (R124) and no stored accent (graders use the default for
`grew_up_hearing`)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..contracts.registry import CorpusFile, default_split, parse_corpus
from .corpus_files import SpeakerInfo

LECT = "cmn"


def corpus_file(
    corpus_id: str, source: str, speakers: list[str], info: Mapping[str, SpeakerInfo], pack: Path
) -> CorpusFile:
    """Validated against the contract and the pack's accents (`parse_corpus` raises `RegistryError`)."""
    rows = []
    for sid in speakers:
        known = info.get(sid, SpeakerInfo())
        row: dict = {"id": sid, "split": default_split("public", sid)}
        if known.background is not None:
            row["background"] = known.background
        if known.grew_up_hearing is not None:
            row["grew_up_hearing"] = known.grew_up_hearing
        rows.append(row)
    data = {"corpus": {"id": corpus_id, "source": source, "kind": "public", "lect": LECT}, "speaker": rows}
    return parse_corpus(data, pack=pack, source=f"corpus {corpus_id!r}")
