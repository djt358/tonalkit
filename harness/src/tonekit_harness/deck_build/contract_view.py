"""What the contract model knows of a card. `text_traditional` (R74) is added to `Card` by C0's fix
round; until it is there, the contract file (TOML) leaves it out so that `load_deck` accepts the
deck, and the kit's JSON, which has no model behind it, keeps it. Once the field exists nothing is
dropped and this module does nothing."""

from __future__ import annotations

from ..contracts.deck import Card

# Optional card fields that arrived with a later contract revision.
NEWER_FIELDS = ("text_traditional",)


def dropped_fields() -> list[str]:
    """The newer fields the `Card` model does not have (yet)."""
    return [f for f in NEWER_FIELDS if f not in Card.model_fields]


def contract_card(card: dict) -> dict:
    """`card` without the fields the model cannot hold yet."""
    drop = dropped_fields()
    return {k: v for k, v in card.items() if k not in drop}
