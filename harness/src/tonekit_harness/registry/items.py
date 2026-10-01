"""One manifest row joined to the corpus and the speaker it belongs to."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..contracts.registry import CorpusMeta, Speaker
from ..manifest import Clip


def qualify(corpus_id: str, name: str) -> str:
    """`corpus/name`: speaker ids (and clip ids) are only unique within their corpus, so across
    corpora they are written with the corpus in front."""
    return f"{corpus_id}/{name}"


@dataclass(frozen=True)
class CorpusClip:
    """A clip of a registered corpus with its `[[speaker]]` entry. `audio_path` is where the WAV
    lives (the manifest's directory plus the clip's path)."""

    corpus: CorpusMeta
    speaker: Speaker
    clip: Clip
    audio_path: Path

    @property
    def qualified_speaker(self) -> str:
        return qualify(self.corpus.id, self.speaker.id)

    @property
    def qualified_id(self) -> str:
        return qualify(self.corpus.id, self.clip.id)

    @property
    def key(self) -> tuple[str, str]:
        """(corpus id, clip id): what makes a clip the same clip in two selections."""
        return (self.corpus.id, self.clip.id)
