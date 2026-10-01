"""Making the deliberate-error twin of a phrase: one character of it is replaced by a real
character of the same syllable and another tone (睡 for 水), taken from the tone-variant lexicon.

The final character goes first. When that would move a neighbour's sandhi (the contract refuses
an error that changes two surface tones, R63), the measure word, the second character, is tried:
一碗水 cannot take 睡 without 碗 turning from wán to wǎn, so it becomes 一湾水. Every candidate is
judged by the contract itself (`accept`), and the reasons the others were refused are returned."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .lexicon import Lexicon, Variant
from .pinyin_render import render
from .reading import RULES, Reading


@dataclass(frozen=True)
class Substitution:
    error: Reading
    variant: Variant
    position: int  # index of the replaced character in the text


def candidate_positions(n: int) -> list[int]:
    """Where to substitute in an n-character 一 + measure word + noun phrase: the last character,
    then the measure word."""
    return list(dict.fromkeys([n - 1, 1]))


def error_reading(correct: Reading, position: int, variant: Variant) -> Reading | None:
    """`correct` with the character at `position` replaced, its pinyin spoken with sandhi applied.
    None when the sandhi of the result is not a single reading (a run of three or more third
    tones), which a source row must then spell out."""
    chars = list(correct.text)
    chars[position] = variant.variant
    text = "".join(chars)
    trad = None
    if correct.text_traditional is not None:
        trad_chars = list(correct.text_traditional)
        trad_chars[position] = variant.variant_traditional
        trad = "".join(trad_chars)
    syllables = correct.citation()
    texts = [s.text for s in syllables]
    texts[position] = variant.variant_pinyin
    citation_pinyin = " ".join(texts)
    cited = RULES.parse_pinyin(citation_pinyin)
    bases = [s.base for s in cited]
    options = RULES.surface_options([s.tone for s in cited], bases, correct.context, text)
    if len(options) != 1:
        return None
    (tones,) = options
    return Reading(text, citation_pinyin, render(bases, tones), correct.context, trad)


def derive_error(
    correct: Reading, lexicon: Lexicon, accept: Callable[[Reading], list[str]]
) -> tuple[Substitution | None, list[str]]:
    """The first lexicon substitution the contract accepts (`accept` returns the problems of an
    error reading, none when it passes), and the reasons the ones tried before it did not."""
    syllables = correct.citation()
    reasons: list[str] = []
    for position in candidate_positions(len(correct.text)):
        char = correct.text[position]
        variants = lexicon.variants(char)
        if not variants:
            reasons.append(f"{char} has no tone variant in the lexicon")
        for v in variants:
            here = syllables[position]
            known = RULES.parse_pinyin(v.pinyin)[0]
            if (here.base, here.tone) != (known.base, known.tone):
                reasons.append(f"{char} is read {here.text} here but the lexicon's {v.variant} is for {v.pinyin}")
                continue
            error = error_reading(correct, position, v)
            if error is None:
                reasons.append(
                    f"the sandhi of {correct.text[:position]}{v.variant}{correct.text[position + 1 :]} is ambiguous"
                )
                continue
            problems = accept(error)
            if not problems:
                return Substitution(error, v, position), reasons
            reasons.append(f"{error.text}: {problems[0]}")
    return None, reasons
