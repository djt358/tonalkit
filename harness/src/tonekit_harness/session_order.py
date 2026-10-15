"""The order each speaker read their clips in (ruling R111).

A manifest lists a session's clips in deck order, but the kit shuffles each pair's cards within
their block, and `session.json` lists the clips in the order they were read (contracts.md section
2; intake keeps a byte-for-byte copy at `sessions/<CODE>.json` beside the manifest). A register
that follows the speaker must see their clips in that order.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from .contracts.bundle import Session
from .intake.layout import clip_id, session_copy
from .manifest import Clip


class SessionOrderError(ValueError):
    """A session file beside the manifest could not be read; the message names it."""


def session_code(clip: Clip) -> str | None:
    """The session a clip intake wrote was read in (its id is `<CODE>-<card>`), or None for a
    clip that was not recorded from a deck."""
    if clip.card is None or not clip.id.endswith(f"-{clip.card}"):
        return None
    code = clip.id[: -len(clip.card) - 1]
    return code if clip_id(code, clip.card) == clip.id else None


def _session(root: Path, code: str) -> Session | None:
    # A selection across corpora qualifies clip ids with their corpus (`<corpus>/<CODE>-<card>`,
    # `registry.Selection.grading_clips`) and grades from the corpora directory: the session file
    # is then in that corpus's directory.
    corpus, _, bare = code.rpartition("/")
    path = session_copy(root / corpus if corpus else root, bare)
    if not path.is_file():
        return None
    try:
        return Session.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as e:
        raise SessionOrderError(f"{path}: not a readable session.json: {e}") from e


def reading_order(clips: Sequence[Clip], root: Path) -> dict[str, list[Clip]]:
    """Each speaker's clips (speakers in manifest order) in the order they were read: by session
    start, then by position in that session's `session.json`. A speaker any of whose clips has no
    session file beside the manifest (`root`), or is not listed in it, keeps manifest order.
    Raises `SessionOrderError` for a session file that cannot be read."""
    sessions: dict[str, Session | None] = {}
    out: dict[str, list[Clip]] = {}
    for speaker in dict.fromkeys(c.speaker for c in clips):
        mine = [c for c in clips if c.speaker == speaker]
        keys = []
        for clip in mine:
            code = session_code(clip)
            if code is not None and code not in sessions:
                sessions[code] = _session(root, code)
            session = sessions.get(code) if code is not None else None
            cards = [] if session is None else [c.card for c in session.clips]
            if session is None or clip.card not in cards:
                keys = None
                break
            keys.append((session.started_at, code, cards.index(clip.card)))
        out[speaker] = mine if keys is None else [c for _, c in sorted(zip(keys, mine), key=lambda kc: kc[0])]
    return out
