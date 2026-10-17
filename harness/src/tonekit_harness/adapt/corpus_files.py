"""What a corpus reader finds in a downloaded public corpus: its utterances (audio file and
transcript) and what the corpus says about its speakers. The readers (`aishell3`, `thchs30`) know
their layouts; everything after them is shared."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..contracts.enums import Background, GrewUpHearing
from .reading import Transcript


class AdaptError(ValueError):
    """`tkh adapt` refused (a source not allowed, a layout it does not know, a corpus it would
    overwrite); nothing was written."""


@dataclass(frozen=True)
class Utterance:
    id: str  # the corpus's own utterance id, unique in the corpus
    speaker: str  # the corpus's own speaker id
    audio: Path | None  # None: the corpus has a transcript but no audio file for it
    transcript: Transcript | None  # None: `problem` says why
    problem: str | None = None  # a `drops` reason found while reading the files


@dataclass(frozen=True)
class SpeakerInfo:
    """What the corpus's documentation or metadata says about a speaker (ruling R124)."""

    background: Background | None = None
    grew_up_hearing: GrewUpHearing | None = None


@dataclass
class Found:
    utterances: list[Utterance] = field(default_factory=list)
    speakers: dict[str, SpeakerInfo] = field(default_factory=dict)  # by speaker id; others get SpeakerInfo()


def require_dir(path: Path, what: str, hint: str = "") -> Path:
    """`path`, which must be a directory of the corpus; refused with `what` and `hint` otherwise."""
    if not path.is_dir():
        raise AdaptError(f"{path} is not a directory: expected {what}{hint}")
    return path


def read_text(path: Path) -> str | None:
    """A transcript or metadata file as UTF-8 text (a byte-order mark is skipped); None if it is
    not UTF-8."""
    try:
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
