"""`tkh purge --session CODE [--data DIR]`: delete a session on request, and say what only DJ can
delete himself."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from ..contracts.bundle import SESSION_CODE_PATTERN
from ..evaluate import DEFAULT_CACHE_DIR
from ..repo import repo_root
from .bundle_match import session_bundles
from .errors import IntakeError
from .options import add_data_option, root_from
from .purge import PurgeOutcome, purge_session

RAW_COPIES = Path("harness") / "corpus" / "raw"  # where DJ unzips bundles in the checkout


def _code(text: str) -> str:
    code = text.strip().upper()
    if not re.fullmatch(SESSION_CODE_PATTERN, code):
        raise IntakeError(f"{text!r} is not a session code (six characters, no 0, O, 1 or I)")
    return code


def _done_lines(o: PurgeOutcome) -> list[str]:
    lines = []
    for t in o.corpora:
        lines.append(f"  corpus {t.corpus_id}: removed {t.summary()}; outputs made from it are marked stale")
    if o.staging:
        lines.append(f"  removed {o.staging} unfinished intake staging area(s)")
    if o.inbox:
        lines.append(f"  removed {o.inbox} bundle(s) from inbox/")
    if o.cache_entries:
        lines.append(
            f"  cleared tkh eval's analysis cache ({o.cache_entries} entries in {DEFAULT_CACHE_DIR}): "
            "entries are keyed by a hash, so one session's cannot be picked out"
        )
    lines.append(f"  logged in {o.log} ({o.record.files_removed} session files removed)")
    return lines


def _reminder(code: str, repo: Path) -> list[str]:
    """The last lines of every purge: what the engine cannot reach (contracts section 6)."""
    lines = [
        "What only you can delete: the original zip wherever it reached you (Messages, Mail, AirDrop "
        "or Downloads, Files) and any copy outside the data root, such as an unzipped folder or a backup.",
    ]
    return lines + [f"  still on disk: {p}" for p in session_bundles(repo / RAW_COPIES, code)]


def _run(args: argparse.Namespace) -> int:
    repo = repo_root()
    try:
        root = root_from(args)
        code = _code(args.session)
        outcome = purge_session(root, code, repo=repo, cache_dir=DEFAULT_CACHE_DIR)
    except (IntakeError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if outcome is None:
        print(f"purge {code}: nothing found under {root}; nothing changed")
    else:
        print("\n".join([f"purge {code}"] + _done_lines(outcome)))
        print(f"Reports made from those corpora before now still list {code}'s clips: re-run tkh eval to replace them.")
    print("\n".join(_reminder(code, repo)))
    return 0


def register(subparsers) -> None:
    p = subparsers.add_parser("purge", help="delete a session's recordings and data on request (by its code)")
    p.add_argument("--session", required=True, metavar="CODE", help="the session code the kit showed the speaker")
    add_data_option(p)
    p.set_defaults(func=_run)
