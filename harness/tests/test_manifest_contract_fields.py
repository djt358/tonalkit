"""contracts.md section 4: the optional deck-linking fields of `manifest.Clip`."""

import pytest
from pydantic import ValidationError
from test_manifest import row

from tonekit_harness.manifest import Clip


def test_a_row_without_the_new_fields_still_validates():
    clip = Clip.model_validate(row())
    assert (clip.card, clip.deck, clip.take, clip.context) == (None, None, None, None)


def test_the_new_fields_parse():
    clip = Clip.model_validate(row(card="g01-c", deck="s05-v1", take=2, context="phrase"))
    assert (clip.card, clip.deck, clip.take, clip.context) == ("g01-c", "s05-v1", 2, "phrase")


@pytest.mark.parametrize("context", ["isolated", "phrase"])
def test_both_contexts_are_accepted(context):
    assert Clip.model_validate(row(context=context)).context == context


@pytest.mark.parametrize(
    "field,value", [("context", "solitaire"), ("take", "two"), ("take", 0), ("card", 7), ("deck", ["x"])]
)
def test_bad_values_for_the_new_fields_fail_naming_the_field(field, value):
    with pytest.raises(ValidationError) as e:
        Clip.model_validate(row(**{field: value}))
    assert field in str(e.value)
