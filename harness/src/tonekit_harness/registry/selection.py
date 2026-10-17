"""A selection: clips drawn from any number of corpora, with the speakers and corpora they came from.
`for_fitting()` and `for_gate()` return it as a `FittingSelection` or `GateSelection`, a type that
says the promise was checked: code that fits or issues a verdict takes those, never a bare
`Selection`."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from .. import clearance
from ..contracts.registry import CorpusMeta, Speaker
from ..manifest import Clip
from .accent import accent_for
from .errors import SelectionError
from .items import CorpusClip, qualify
from .refusals import check_fitting, check_gate


@dataclass(frozen=True)
class Selection:
    """The result of `DataRoot.select`: `items` in corpus-id order, then manifest order (a union
    keeps its first operand's items first). `audio_root` is the directory the grading clips' paths
    are relative to."""

    audio_root: Path
    items: tuple[CorpusClip, ...] = ()

    def __len__(self) -> int:
        return len(self.items)

    @property
    def corpora(self) -> dict[str, CorpusMeta]:
        """The corpora the clips came from, by id."""
        return {i.corpus.id: i.corpus for i in self.items}

    @property
    def speakers(self) -> dict[str, Speaker]:
        """The speakers the clips came from, by qualified id (`corpus/speaker`)."""
        return {i.qualified_speaker: i.speaker for i in self.items}

    @property
    def clips(self) -> list[Clip]:
        """The manifest rows as written: ids, speakers and paths are the corpus's own."""
        return [i.clip for i in self.items]

    def grading_clips(self) -> list[Clip]:
        """Clips to hand to `evaluate.run(..., root=selection.audio_root)`: clip, speaker and pair
        ids are qualified with their corpus (`corpus/id`, so two corpora can use the same ones) and
        each path is relative to `audio_root`."""
        return [
            i.clip.model_copy(
                update={
                    "id": i.qualified_id,
                    "speaker": i.qualified_speaker,
                    "pair": None if i.clip.pair is None else qualify(i.corpus.id, i.clip.pair),
                    "path": i.audio_path.relative_to(self.audio_root).as_posix(),
                }
            )
            for i in self.items
        ]

    def accents(self, override: str | None = None) -> dict[str, str]:
        """Each speaker's accent by qualified id; `override` (evaluate's `--accent`) wins."""
        return {
            i.qualified_speaker: accent_for(i.speaker, i.corpus.lect, override=override)
            for i in self.items
        }

    def of_speakers(self, speakers: Collection[str]) -> Selection:
        """Only the clips of `speakers` (qualified `corpus/speaker` ids), which must all be here:
        a speaker who is not is a `SelectionError`, never a silently smaller selection."""
        missing = sorted(set(speakers) - set(self.speakers))
        if missing:
            have = ", ".join(self.speakers) or "none"
            raise SelectionError(f"speaker(s) {', '.join(missing)} not in the selection (speakers: {have})")
        return Selection(self.audio_root, tuple(i for i in self.items if i.qualified_speaker in speakers))

    def __or__(self, other: Selection) -> Selection:
        """The union: this selection's clips, then the other's that are not already here (the same
        corpus and clip id). `calib` of the public corpora with `gate` of the volunteers is
        `public_calib | volunteer_gate`. The union of checked selections is unchecked again."""
        if self.audio_root != other.audio_root:
            raise ValueError(f"selections from different data roots ({self.audio_root}, {other.audio_root})")
        have = {i.key for i in self.items}
        return Selection(self.audio_root, self.items + tuple(i for i in other.items if i.key not in have))

    def for_fitting(self, register: Mapping[str, str] | None = None) -> FittingSelection:
        """This selection, if anything may be fitted on it. Raises `RefusalError` for a gate or
        heldout speaker, a source the register does not clear, or an empty selection. `register`
        is `clearance.read_register`'s (default: the checkout's data-register.csv)."""
        check_fitting(self.items, _register(register))
        return FittingSelection(self.audio_root, self.items)

    def for_gate(self, register: Mapping[str, str] | None = None) -> GateSelection:
        """This selection, if a gate verdict may be issued on it. Raises `RefusalError` for
        synthetic corpora or clips, a source the register does not clear, or an empty selection."""
        check_gate(self.items, _register(register))
        return GateSelection(self.audio_root, self.items)


@dataclass(frozen=True)
class FittingSelection(Selection):
    """A selection `for_fitting` checked: no gate or heldout speaker, every source cleared."""


@dataclass(frozen=True)
class GateSelection(Selection):
    """A selection `for_gate` checked: real recordings only, every source cleared."""


def _register(register: Mapping[str, str] | None) -> Mapping[str, str]:
    return clearance.read_register(None) if register is None else register
