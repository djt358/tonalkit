"""What `tkh relabel` prints: what the file decided, each row it changed and why, and what to run
next. Clip ids appear here (DJ's terminal), never in the stale marker or the purge log."""

from __future__ import annotations

from collections import Counter

from ..contracts.relabel import RowChange
from ..intake import layout
from ..intake.summary import eval_command
from ..manifest import Clip
from .apply import Outcome

VERDICTS = {"as_card": "as the card says", "heard": "heard other tones", "unclear": "unclear", "exclude": "exclude"}


def _reading(row: Clip) -> str:
    return f"{row.label} {' '.join(row.produced_tones or row.intended.tones)}"


def describe(change: RowChange) -> str:
    """One change to a row, in words."""
    before, after = change.before, change.after
    if after is None:
        return "excluded (its audio stays until purge)"
    if before is None:
        return f"back in the manifest: {_reading(after)}" + (f", pair {after.pair}" if after.pair else "")
    parts = []
    if _reading(before) != _reading(after):
        parts.append(f"{_reading(before)} -> {_reading(after)}")
    if before.pair != after.pair:
        parts.append(f"leaves pair {before.pair}" if after.pair is None else f"back in pair {after.pair}")
    if before.needs_listen != after.needs_listen:
        parts.append("flagged for another listen (unclear)" if after.needs_listen else "listen flag cleared")
    return "; ".join(parts) or "changed"


def outcome_lines(o: Outcome, source: str, who: str, decided: int) -> list[str]:
    plan = o.plan
    head = f"relabel {o.state.corpus_id} from {source} ({decided} decisions by {who})"
    if plan.nothing:
        lines = [f"{head}: nothing to change; every decision in it is already applied"]
    else:
        counts = Counter(d.verdict for d in plan.new.values())
        kinds = ", ".join(f"{VERDICTS[v]} {n}" for v, n in counts.items())
        lines = [head, f"  new decisions: {len(plan.new)}" + (f" ({kinds})" if kinds else "")]
        lines.append(f"  rows changed: {len(plan.changes)}")
        lines += [f"    {cid}: {describe(ch)}" for cid, ch in plan.changes.items()]
        if plan.half_pairs:
            lines.append(
                f"  pairs left out of the gate (no longer one correct and one error reading; "
                f"the clips stay for fitting): {', '.join(plan.half_pairs)}"
            )
    if plan.older:
        lines.append(f"  skipped {len(plan.older)} decision(s) older than the one already applied: {', '.join(plan.older)}")
    if plan.unknown:
        lines.append(f"  skipped {len(plan.unknown)} decision(s) for clips not in the corpus (purged?)")
    if not plan.nothing:
        lines.append(f"  logged in {o.log}")
    if o.stale is not None:
        lines.append(f"  outputs made from the corpus are marked stale ({o.stale})")
    return lines


def next_lines(o: Outcome, pack, root) -> list[str]:
    """The commands to run after rows changed: grade the corpus again, then look at the page."""
    cid = o.state.corpus_id
    command = eval_command(o.state.manifest, pack, layout.report_path(root, cid), layout.results_path(root, cid))
    return [
        "",
        "next, from harness/: grade the relabelled corpus, then rebuild the page",
        f"  {command}",
        f"  uv run tkh review --corpus {cid} --data {root}",
    ]
