"""Registers that follow the speaker (ruling R111): `tkh eval --register-from rolling`.

Each speaker's clips are graded causally, as Bendy would meet them: first the 妈麻马骂 drill
clips, then the rest in the order they were read (`session_order`). Each clip is graded with the
register rolled from the drill and that speaker's earlier clips only, never later ones, and is
then rolled in (`tonekit_py.roll_register`, under the calibration's `rolling_register`
parameters). A clip that measured nothing teaches nothing.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import tonekit_py

from .manifest import Clip
from .register_json import register_json
from .session_order import reading_order

if TYPE_CHECKING:  # evaluate imports this module
    from .evaluate import Grader, Result


def causal_order(clips: Sequence[Clip], root: Path) -> list[Clip]:
    """Every clip in the order a rolling register meets it: speaker by speaker, the drill clips
    (set `register`) first, then the rest, each part in reading order."""
    out: list[Clip] = []
    for ordered in reading_order(clips, root).values():
        out += [c for c in ordered if c.set == "register"]
        out += [c for c in ordered if c.set != "register"]
    return out


def rolling_registers(
    clips: Sequence[Clip], grader: Grader
) -> tuple[dict[str, str | None], dict[str, Result]]:
    """Clip id -> the register JSON its clip was graded with (None: a cold start, nothing rolled
    in yet), and every clip's result, graded on the way."""
    registers: dict[str, str | None] = {}
    by_id: dict[str, Result] = {}
    rolling: dict[str, str] = {}  # speaker -> RollingRegister JSON, once it has learnt something
    for clip in causal_order(clips, grader.root):
        previous = rolling.get(clip.speaker)
        given = None if previous is None else register_json(json.loads(previous)["register"])
        analysis = grader.analysis(clip, given)
        result, assessment = grader.assess(clip, analysis)
        registers[clip.id], by_id[clip.id] = given, result
        rolled = tonekit_py.roll_register(
            previous, analysis, json.dumps(assessment), grader.pack_toml, grader.calib_json
        )
        if json.loads(rolled)["register"]["n_syllables"] > 0:
            rolling[clip.speaker] = rolled
    return registers, by_id
