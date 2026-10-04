"""corpus.toml as text (docs/s05/contracts.md section 3), written from the validated model so the
file always reads back as the same `CorpusFile`. Comments in a hand-edited file are not kept."""

from __future__ import annotations

from ..contracts.registry import CorpusFile
from ..toml_write import toml_value


def corpus_toml_text(corpus: CorpusFile) -> str:
    """`[corpus]`, then one `[[speaker]]` per speaker; unset optional fields are left out."""
    data = corpus.model_dump(exclude_none=True)
    lines = ["[corpus]"] + [f"{k} = {toml_value(v)}" for k, v in data["corpus"].items()]
    for speaker in data["speaker"]:
        lines += ["", "[[speaker]]"] + [f"{k} = {toml_value(v)}" for k, v in speaker.items()]
    return "\n".join(lines) + "\n"
