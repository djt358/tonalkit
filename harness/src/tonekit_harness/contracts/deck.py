"""The prompt deck (`kit/deck/<id>.toml`, contracts.md section 1): what each card shows and what a
correct or deliberately wrong reading of it is. The models enforce the rules of the contract."""

from __future__ import annotations

import hashlib
import tomllib
from pathlib import Path
from textwrap import indent
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, ValidationError, ValidationInfo, model_validator

from ..manifest import Candidate, CardLabel, CardSet, Context
from .base import StrictModel, format_validation_error
from .deck_rules import deck_problems, fmt
from .deck_sets import CORRECT_ONLY_SETS, PAIR_SETS
from .pack import PackInfo, load_pack_info

_ID = r"^[a-z0-9-]+$"
_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DeckError(ValueError):
    """A deck could not be read or breaks a rule; the message starts with its source."""


class DeckMeta(StrictModel):
    id: str = Field(pattern=_ID)
    lect: str = Field(min_length=1)
    version: int = Field(ge=1)
    title: _Text


class Card(StrictModel):
    id: str = Field(pattern=_ID)  # unique in the deck
    set: CardSet
    pair: str | None = Field(default=None, pattern=_ID)
    label: CardLabel
    text: _Text  # what the card shows
    pinyin: _Text  # the surface (spoken) form, sandhi applied
    citation_pinyin: _Text  # the dictionary form, for the sandhi check
    context: Context
    intended: Candidate
    produced_tones: list[str]  # what the card asks to be said
    distractors: list[Candidate] = []
    prompt_note: str = ""
    status: Literal["unverified", "approved"] = "unverified"  # `approved` is DJ's audit only

    @model_validator(mode="after")
    def _own_rules(self) -> Card:
        problems = self._shape_problems() + self._label_problems()
        if problems:
            raise ValueError("\n".join(f"card {self.id!r}: {p}" for p in problems))
        return self

    def _shape_problems(self) -> list[str]:
        problems = []
        if self.set in PAIR_SETS and self.pair is None:
            problems.append(f"set {self.set!r} needs a pair")
        if not self.intended.tones:
            problems.append("intended has no tones")
        for c in [self.intended, *self.distractors]:
            if len(c.tones) != len(c.labels):
                name = "intended" if c is self.intended else f"distractor {c.id!r}"
                problems.append(f"{name} has {len(c.tones)} tones but {len(c.labels)} labels")
        if len(self.produced_tones) != len(self.intended.tones):
            problems.append(
                f"produced_tones has {len(self.produced_tones)} tones "
                f"but intended has {len(self.intended.tones)}"
            )
        return problems

    def _label_problems(self) -> list[str]:
        if self.set in CORRECT_ONLY_SETS and self.label != "correct":
            return [f"set {self.set!r} cards must be correct readings, not {self.label}"]
        if len(self.produced_tones) != len(self.intended.tones):
            return []
        differing = sum(p != i for p, i in zip(self.produced_tones, self.intended.tones, strict=True))
        if self.label == "correct" and differing:
            return [
                f"label is correct but produced_tones {fmt(self.produced_tones)} "
                f"differ from intended {fmt(self.intended.tones)}"
            ]
        if self.label == "tone_error" and differing != 1:
            return [
                f"label is tone_error but produced_tones differ from intended in {differing} "
                f"positions ({fmt(self.produced_tones)} against {fmt(self.intended.tones)}); "
                "it needs exactly one"
            ]
        return []


class Deck(StrictModel):
    deck: DeckMeta
    card: list[Card] = Field(min_length=1)

    @model_validator(mode="after")
    def _across_cards(self, info: ValidationInfo) -> Deck:
        # The tone inventory is the pack's: pass it as validation context (`parse_deck` does);
        # without, the default pack (packs/cmn/cmn.toml) stands in.
        pack = (info.context or {}).get("pack") or load_pack_info(None)
        problems = deck_problems(self, pack)
        if problems:
            raise ValueError("\n".join(problems))
        return self


def parse_deck(data: dict, *, pack: str | Path | PackInfo | None = None, source: str = "deck") -> Deck:
    """Validate a deck's data (its TOML as a dict) against the contract and the tone inventory of
    `pack` (a pack TOML path; default packs/cmn/cmn.toml). Raises `DeckError` listing every problem."""
    info = pack if isinstance(pack, PackInfo) else load_pack_info(pack)
    try:
        return Deck.model_validate(data, context={"pack": info})
    except ValidationError as e:
        problems = format_validation_error(e, data, {"card": "id"})
        raise DeckError(f"{source}: invalid deck\n{indent(problems, '  ')}") from e


def load_deck(path: str | Path, *, pack: str | Path | None = None) -> Deck:
    """Read and validate the deck TOML at `path` (see `parse_deck`)."""
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise DeckError(f"{path}: invalid TOML: {e}") from e
    return parse_deck(data, pack=pack, source=str(path))


def deck_sha256(path: str | Path) -> str:
    """The hash of the deck file's bytes: what a session bundle records as `deck.sha256`."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
