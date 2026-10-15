"""corpus.toml written from the model reads back as the same model."""

from __future__ import annotations

import pytest

from tonekit_harness.contracts.registry import parse_corpus
from tonekit_harness.intake.corpus_toml import corpus_toml_text
from tonekit_harness.toml_write import toml_value

CORPUS = {
    "corpus": {"id": "volunteers-s05-v1", "source": "volunteer-corpus", "kind": "recorded", "lect": "cmn"},
    "speaker": [
        {"id": "v-k7q2md", "background": "native", "grew_up_hearing": "taiwan", "split": "gate", "sessions": ["K7Q2MD"]},
        {"id": "dj", "accent": "cmn-TW", "split": "dev", "sessions": []},
    ],
}


def test_the_text_reads_back_as_the_same_corpus():
    import tomllib

    corpus = parse_corpus(CORPUS)
    text = corpus_toml_text(corpus)
    assert parse_corpus(tomllib.loads(text)) == corpus
    assert "background" not in text.split('id = "dj"')[1]  # unset fields are left out


def test_a_corpus_with_no_speakers_has_only_its_table():
    text = corpus_toml_text(parse_corpus({"corpus": CORPUS["corpus"]}))
    assert text.startswith("[corpus]\n") and "[[speaker]]" not in text


@pytest.mark.parametrize("value", [True, 1.5, None])
def test_values_toml_files_here_never_hold_are_refused(value):
    with pytest.raises(TypeError):
        toml_value(value)
