"""Which deck sets carry which rules (contracts.md section 1); the card and the deck rules share them."""

from __future__ import annotations

# Sets graded as correct/tone_error pairs (R81): every card names its pair, and each pair is one
# correct and one tone_error card of the same intended reading. In the other sets `pair` only
# groups cards.
PAIR_SETS = frozenset({"gate", "diag_t23"})

# Sets of correct readings only (R76): the members of a minimal set (different words, each naming
# another as a distractor) and the contrasts of a context set (citation against sandhi).
CORRECT_ONLY_SETS = frozenset({"diag_minimal", "diag_context"})
