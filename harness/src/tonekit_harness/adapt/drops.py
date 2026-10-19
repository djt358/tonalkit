"""Why an utterance of a public corpus gets no row (ruling R122), and the tally `tkh adapt` prints.

A wrong produced tone in fitting data silently poisons the templates, so anything whose spoken
tones the transcript does not settle is dropped, and counted by reason."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

# The transcript
MALFORMED = "malformed transcript (tokens or lines do not line up)"
NON_MANDARIN = "non-Mandarin token (not a hanzi, or not a pinyin syllable)"
NO_TONE = "a syllable with no tone digit"
ERHUA = "erhua"
# Tones the transcript does not settle
NEUTRAL_YI_BU = "一 or 不 before a neutral syllable"
NEUTRAL_REDUPLICATION = "a third or second tone before its own reduplication in the neutral tone"
MIXED = "dictionary and sandhi tones mixed in one transcript"
INCONSISTENT = "sandhi tones no citation reading explains"
MANY_READINGS = "more than one native reading (R89)"
THIRD_TONES = "third tones in a row in a per-recording transcript"
YI_BU_DICTIONARY = "一 or 不 in its dictionary tone where the checker applies sandhi"
T3_ACROSS_WORDS = "third-tone sandhi across a word boundary, or with no word boundaries"
# The clip
TOO_LONG = "longer than --max-syllables"
NO_AUDIO = "no audio file"
BAD_AUDIO = "audio not readable"
NO_TRANSCRIPT = "no transcript"

EXAMPLES = 3  # utterance ids kept per reason, to look up in the corpus


@dataclass
class Drops:
    """How many utterances were dropped for each reason, with the first few ids."""

    counts: Counter[str] = field(default_factory=Counter)
    examples: dict[str, list[str]] = field(default_factory=dict)

    def add(self, reason: str, utterance: str) -> None:
        self.counts[reason] += 1
        kept = self.examples.setdefault(reason, [])
        if len(kept) < EXAMPLES:
            kept.append(utterance)

    @property
    def total(self) -> int:
        return sum(self.counts.values())
