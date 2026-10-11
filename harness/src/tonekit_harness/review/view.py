"""The data the review page shows, one entry per clip in page order: who said it, what the card
showed and asked for, a relative link to its audio, the scorer's view, what the manifest says now
and the decision already applied. Every path in it is relative to the page, and only to files
under the data root."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath
from urllib.parse import quote

from ..contracts.pack import load_pack_info
from ..deck_build.pinyin_render import render_syllable
from ..eval_results import EvalResults, ResultsError, load_results
from ..intake import layout
from ..intake.packs import pack_path
from ..intake.trace import corpus_document
from ..manifest import Clip
from ..relabel.pairs import twins
from ..relabel.rules import card_tones
from ..relabel.state import ClipState, CorpusState, corpus_state, session_of
from .cards import ReviewError, Shown, shown_cards
from .order import review_order
from .scorer import GROUP_NAMES, ScorerView, scorer_view

PAGE_SCHEMA = "tonekit.review-page.v1"


@dataclass(frozen=True)
class ReviewOptions:
    root: Path  # the data root
    corpus_id: str
    repo: Path
    results: Path | None = None  # None: the default results file, if there is one
    deck: Path | None = None  # the deck JSON, when the repository does not have it
    speakers: tuple[str, ...] = ()  # speaker ids or session codes; empty: all
    sets: tuple[str, ...] = ()  # empty: all


def _results(opts: ReviewOptions) -> tuple[EvalResults | None, Path | None]:
    path = opts.results or layout.results_path(opts.root, opts.corpus_id)
    if opts.results is None and not path.is_file():
        return None, None
    try:
        return load_results(path), path
    except ResultsError as e:
        raise ReviewError(str(e)) from e


def _audio(state: CorpusState, row: Clip, page_dir: Path, root: Path) -> str | None:
    """The clip's audio relative to the page, or None when it is missing or outside the data root."""
    target = Path(os.path.normpath(state.manifest.parent / row.path))
    if not target.is_relative_to(Path(os.path.normpath(root))) or not target.is_file():
        return None
    return quote(PurePath(os.path.relpath(target, page_dir)).as_posix())


def _forms(label: str, tones: list[str]) -> dict[str, str]:
    out = {}
    for t in tones:
        try:
            out[t] = render_syllable(label, t)
        except ValueError:  # no vowel to mark, or an unknown tone id
            out[t] = f"{label}{t}"
    return out


def _shown_text(shown: Shown | None) -> dict:
    if shown is None:
        return {"text": "", "traditional": "", "script": None, "pinyin_shown": None, "note": "", "twin": None, "pinyin": ""}
    card, traditional = shown.card, shown.script == "traditional"
    note = (card.prompt_note_traditional or card.prompt_note) if traditional else card.prompt_note
    twin = shown.twin
    return {
        "text": card.text,
        "traditional": card.text_traditional or card.text,
        "script": shown.script,
        "pinyin_shown": shown.reading == "hanzi+pinyin",
        "note": note,
        "twin": None if twin is None else ((twin.text_traditional or twin.text) if traditional else twin.text),
        "pinyin": card.pinyin,
    }


def _now(st: ClipState) -> dict | None:
    """What the manifest says now, when a relabel changed it."""
    if st.current == st.original:
        return None
    if st.current is None:
        return {"excluded": True}
    return {
        "excluded": False,
        "label": st.current.label,
        "tones": card_tones(st.current),
        "left_pair": st.original.pair is not None and st.current.pair is None,
        "needs_listen": st.current.needs_listen,
    }


def _clip(cid: str, st: ClipState, shown: Shown | None, view: ScorerView, ctx: dict) -> dict:
    row = st.original
    text = _shown_text(shown)
    script_text = text["traditional"] if text["script"] == "traditional" else text["text"]
    labels = list(row.intended.labels) + [""] * (len(row.intended.tones) - len(row.intended.labels))
    hanzi = list(script_text) if len(script_text) == len(labels) else [None] * len(labels)
    syllables = [
        {
            "label": label,
            "hanzi": hanzi[i],
            "forms": _forms(label, ctx["tones"]),
            "heard": view.syllables[i].heard if view.syllables else None,
            "p": view.syllables[i].p_correct if view.syllables else None,
            "note": view.syllables[i].note if view.syllables else None,
        }
        for i, label in enumerate(labels)
    ]
    current = st.current if st.current is not None else row  # an excluded clip's audio is still there
    return {
        "id": cid,
        "session": session_of(cid),
        "speaker": row.speaker,
        "about": ctx["speakers"].get(row.speaker, ""),
        "set": row.set,
        "card": row.card,
        "label": row.label,
        **text,
        "audio": _audio(ctx["state"], current, ctx["page_dir"], ctx["root"]),
        "tones": card_tones(row),
        "intended": list(row.intended.tones),
        "syllables": syllables,
        "group": view.group,
        "group_name": GROUP_NAMES[view.group],
        "doubt": view.doubt,
        "overall": view.overall,
        "now": _now(st),
        "applied": None if st.applied is None else st.applied.model_dump(mode="json", exclude={"who"}),
    }


def _speakers(root: Path, corpus_id: str) -> dict[str, str]:
    doc = corpus_document(root, corpus_id)
    out = {}
    for s in doc.get("speaker") or []:
        if isinstance(s, dict) and "id" in s:
            out[str(s["id"])] = ", ".join(str(s[k]) for k in ("background", "grew_up_hearing") if s.get(k))
    return out


def _selected(st: ClipState, opts: ReviewOptions) -> bool:
    row = st.original
    wanted = {s.lower() for s in opts.speakers}
    code = (session_of(st.id) or "").lower()
    if wanted and row.speaker.lower() not in wanted and code not in wanted:
        return False
    return not opts.sets or row.set in opts.sets


def page_data(opts: ReviewOptions, *, now: datetime | None = None) -> dict:
    """Everything the page shows. Raises `ReviewError` (or `RelabelError`) when the corpus, its
    decks or the results cannot be read, or the filters leave no clip."""
    state = corpus_state(opts.root, opts.corpus_id)
    selected = {cid: st for cid, st in state.clips.items() if _selected(st, opts)}
    if not selected:
        raise ReviewError(f"no clips in corpus {opts.corpus_id!r} for the speakers and sets asked for")
    shown = shown_cards(state, repo=opts.repo, deck=opts.deck)
    results, results_path = _results(opts)
    by_id = {c.id: c for c in results.clips} if results else {}
    originals = state.originals
    twin_of = twins(originals)
    views = {
        cid: scorer_view(
            st.original, by_id.get(cid), card_tones(originals[twin_of[cid]]) if cid in twin_of else None
        )
        for cid, st in selected.items()
    }
    tones = sorted(load_pack_info(pack_path(opts.repo, state.lect)).tone_ids) if state.lect else []
    page_dir = layout.review_dir(opts.root, opts.corpus_id)
    ctx = {"state": state, "page_dir": page_dir, "root": opts.root, "tones": tones,
           "speakers": _speakers(opts.root, opts.corpus_id)}  # fmt: skip
    order = review_order(list(selected), views)
    clips = [_clip(cid, selected[cid], shown.get(cid), views[cid], ctx) for cid in order]
    return {
        "schema": PAGE_SCHEMA,
        "corpus": opts.corpus_id,
        "generated_at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "sessions": sorted({c for cid in state.clips if (c := session_of(cid)) is not None}),
        "tones": tones,
        "filters": {"speakers": list(opts.speakers), "sets": list(opts.sets)},
        "results": None
        if results is None or results_path is None
        else {
            "file": _relative_name(results_path, opts.root),
            "register_from": results.register_from,
        },
        "clips": clips,
    }


def _relative_name(path: Path, root: Path) -> str:
    """A file's name for the page: relative to the data root when it is under it, else its name
    alone (the page never shows an absolute path)."""
    p = Path(os.path.normpath(path.absolute()))
    base = Path(os.path.normpath(root))
    return p.relative_to(base).as_posix() if p.is_relative_to(base) else p.name
