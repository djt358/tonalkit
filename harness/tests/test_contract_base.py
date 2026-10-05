"""contracts.base: strict models, and validation errors that name the item they are about."""

import pytest
from pydantic import ValidationError, model_validator

from tonekit_harness.contracts.base import StrictModel, format_validation_error


class Item(StrictModel):
    id: str
    n: int

    @model_validator(mode="after")
    def _n_is_small(self) -> "Item":
        if self.n > 9:
            raise ValueError(f"item {self.id!r}: n is too big")
        return self


class Box(StrictModel):
    item: list[Item]


def errors(data: dict) -> str:
    with pytest.raises(ValidationError) as e:
        Box.model_validate(data)
    return format_validation_error(e.value, data, {"item": "id"})


def test_unknown_keys_are_errors():
    with pytest.raises(ValidationError, match="Extra inputs"):
        Item.model_validate({"id": "a", "n": 1, "m": 2})


def test_a_field_error_names_the_item_by_its_id():
    assert errors({"item": [{"id": "a", "n": 1}, {"id": "b", "n": "x"}]}).startswith(
        "item 'b'.n: Input should be a valid integer"
    )


def test_an_item_level_check_is_just_its_own_message():
    assert errors({"item": [{"id": "a", "n": 10}]}) == "item 'a': n is too big"


def test_an_item_without_an_id_keeps_its_index():
    assert errors({"item": [{"n": 1}]}) == "item.0.id: Field required"


def test_every_problem_is_listed_one_per_line():
    out = errors({"item": [{"id": "a", "n": 10}, {"id": "b", "n": 11}]})
    assert out.splitlines() == ["item 'a': n is too big", "item 'b': n is too big"]


def test_without_the_raw_data_the_path_is_used():
    with pytest.raises(ValidationError) as e:
        Box.model_validate({"item": [{"id": "a", "n": "x"}]})
    assert format_validation_error(e.value).startswith("item.0.n: ")
