"""Writing a fitted pack (ruling R109): the seed pack with its base accent's full-tone
realisations and its tolerance replaced by fitted ones, rendered back to TOML."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Sequence

import numpy as np

from .templates import FULL_TONES, Spread, Template, expand


def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(x)}" for k, x in v.items()) + " }"
    raise TypeError(f"cannot write {type(v).__name__} as TOML")


def _key(k: str) -> str:
    return k if k.replace("_", "").replace("-", "").isalnum() and k.isascii() else json.dumps(k)


def _table(lines: list[str], header: str, table: dict, skip: Sequence[str] = ()) -> None:
    lines.append(header)
    lines.extend(f"{_key(k)} = {_value(v)}" for k, v in table.items() if k not in skip)
    lines.append("")


def render(pack: dict, header_comment: str) -> str:
    """The pack (as `tomllib` reads one) as TOML text, in the schema's order."""
    lines = [f"# {line}" if line else "#" for line in header_comment.splitlines()] + [""]
    _table(lines, "[pack]", pack["pack"])
    for tone in pack.get("tone", []):
        _table(lines, "[[tone]]", tone)
    _table(lines, "[tolerance]", pack["tolerance"])
    for u in pack.get("unvoiced_ok", []):
        _table(lines, "[[unvoiced_ok]]", u)
    if "confusions" in pack:
        _table(lines, "[confusions]", pack["confusions"])
    for accent in pack.get("accent", []):
        _table(lines, "[[accent]]", accent, skip=("realize", "tolerance"))
        for rule in accent.get("realize", []):
            _table(lines, "[[accent.realize]]", rule)
        if "tolerance" in accent:
            _table(lines, "[accent.tolerance]", accent["tolerance"])
    return "\n".join(lines).rstrip("\n") + "\n"


def _is_full_tone_place_rule(rule: dict) -> bool:
    when = rule.get("when", {})
    return when.get("tone") in FULL_TONES and set(when) <= {"tone", "phrase_final"}


def fitted_pack(
    seed_toml: str,
    templates: Sequence[Template],
    spread: Spread | None,
    component: float | None = None,
) -> dict:
    """The seed pack with its base accent's realisations of the full tones by place (rules whose
    `when` names a full tone and at most `phrase_final`) replaced by one rule per fitted template,
    labelled `t<tone>-final` or `t<tone>-medial`, and its tolerance's contour, onset and offset σ
    replaced by `spread`'s. Everything else (citations, the neutral tone's rules, other accents,
    which inherit the fitted rules unless they override them) is kept.

    With `component` w (0 < w < 1), each fitted template is instead added to the seed's own
    realisation of its tone and place (`seed_components`) as a mixture component of weight w,
    the seed's keeping 1 - w between them, and the tolerance stays the seed's: the fitted shape
    is credited as one more way to say the tone, and the published one still scores as it did
    (spec §6.1, realisations as a weighted mixture)."""
    pack = tomllib.loads(seed_toml)
    base = pack["pack"]["base_accent"]
    accent = next(a for a in pack["accent"] if a["id"] == base)
    kept = [r for r in accent.get("realize", []) if not _is_full_tone_place_rule(r)]
    seed = seed_components(seed_toml)
    fitted = []
    for t in templates:
        rule = {
            "label": f"t{t.tone}-{'final' if t.final else 'medial'}",
            "when": {"tone": t.tone, "phrase_final": t.final},
        }
        if component is None:
            rule["chao"] = list(t.knots)
        else:
            rule["mixture"] = [
                {"chao": chao, "weight": round((1.0 - component) * w, 4)} for chao, w in seed[(t.tone, t.final)]
            ] + [{"chao": list(t.knots), "weight": round(component, 4)}]
        fitted.append(rule)
    accent["realize"] = fitted + kept
    if spread is not None and component is None:
        pack["tolerance"].update(contour=spread.contour, onset=spread.onset, offset=spread.offset)
    return pack


def _seed_rule(pack: dict, tone: str, final: bool) -> dict | None:
    """The base accent's most specific prev-free rule for `tone` at the end of a phrase (`final`)
    or elsewhere, or None."""
    base = pack["pack"]["base_accent"]
    accent = next(a for a in pack["accent"] if a["id"] == base)
    rules = [
        r
        for r in accent.get("realize", [])
        if r["when"].get("tone", tone) == tone
        and r["when"].get("phrase_final", final) == final
        and "prev" not in r["when"]
    ]
    return max(rules, key=lambda r: len(r["when"]), default=None)


def seed_components(seed_toml: str) -> dict[tuple[str, bool], list[tuple[list[float], float]]]:
    """The seed pack's realisation of each full tone at the end of a phrase and elsewhere under its
    base accent, with no previous tone, as (Chao knots, weight) components: the most specific
    matching rule's (a mixture's components, or its one contour), else the citation."""
    pack = tomllib.loads(seed_toml)
    citations = {t["id"]: t["chao"] for t in pack["tone"]}
    out = {}
    for tone in FULL_TONES:
        for final in (False, True):
            rule = _seed_rule(pack, tone, final)
            if rule is None:
                out[(tone, final)] = [(list(citations[tone]), 1.0)]
            elif "mixture" in rule:
                out[(tone, final)] = [(list(m["chao"]), float(m["weight"])) for m in rule["mixture"]]
            else:
                out[(tone, final)] = [(list(rule["chao"]), 1.0)]
    return out


def seed_expectations(seed_toml: str) -> dict[tuple[str, bool], np.ndarray]:
    """The seed pack's expected contour (10 points) of each full tone at the end of a phrase and
    elsewhere under its base accent, with no previous tone: `seed_components` averaged by weight.
    The prior that fitted templates are shrunk towards."""
    return {
        key: sum(w * expand(chao) for chao, w in comps)
        for key, comps in seed_components(seed_toml).items()
    }
