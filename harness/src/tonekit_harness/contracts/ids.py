"""The one pattern for ids in the deck and the bundle: lower-case letters, digits and dashes. A card
id names a deck card, a `clips/<card id>.wav` member of a bundle, and an entry of `skipped`."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

CARD_ID_CHARS = "[a-z0-9-]+"  # unanchored: also builds the bundle's clip member pattern
CARD_ID_PATTERN = f"^{CARD_ID_CHARS}$"  # for pydantic fields (deck, pair and card ids)

CardId = Annotated[str, Field(pattern=CARD_ID_PATTERN)]
