"""`tkh fit`'s tone templates, spreads and fitted pack (ruling R109), on hand-built observations
and the shipped seed pack."""

from __future__ import annotations

import math
import tomllib
from pathlib import Path

import numpy as np
import pytest
import tonekit_py

from tonekit_harness.fit.observe import SHAPE, Observation
from tonekit_harness.fit.packfile import fitted_pack, render, seed_expectations
from tonekit_harness.fit.templates import (
    MIN_GROUP,
    Spread,
    Template,
    expand,
    fit_spread,
    fit_templates,
    knots_of,
    usable,
)

PACKS = Path(__file__).resolve().parents[2] / "packs" / "cmn"


def shape(contour) -> dict:
    contour = [float(v) for v in contour]
    return {"contour": contour, "voiced_weights": [1.0] * 10, "onset": contour[0], "offset": contour[-1]}


def obs(
    tone: str, contour, *, final=False, clean=True, label="correct", kind=SHAPE, creaky=False
) -> Observation:
    return Observation("c", "s", label, clean, tone, 0, 3, None, final, kind, shape(contour), creaky)


def line(a: float, b: float) -> np.ndarray:
    return np.linspace(a, b, 10)


def test_only_clean_correct_shaped_full_tones_are_fitted_on():
    good = obs("4", line(5, 1))
    assert usable(good)
    assert not usable(obs("4", line(5, 1), clean=False))
    assert not usable(obs("4", line(5, 1), label="tone_error"))
    assert not usable(obs("4", line(5, 4), creaky=True))  # a contour cut short by creak (R108)
    assert not usable(obs("5", line(3, 3)))
    assert not usable(Observation("c", "s", "correct", True, "4", 0, 3, None, False, SHAPE, None))
    assert not usable(obs("4", [math.nan] * 10))


def test_a_template_is_the_median_contour_at_five_knots():
    # Six medial tone 4s falling from 5 to 2, 3, ..., and one wild one the median ignores.
    falls = [obs("4", line(5, end)) for end in (1, 1.5, 2, 2, 2.5, 3)] + [obs("4", line(1, 5))]
    (medial,) = [t for t in fit_templates(falls) if not t.final]
    assert medial.tone == "4" and medial.n == 7
    assert medial.knots == knots_of(np.median([o.shape["contour"] for o in falls], axis=0))
    assert medial.knots[0] == 5.0 and medial.knots[-1] == 2.0
    assert len(medial.knots) == 5


def test_a_thin_place_pools_both_places():
    medial = [obs("1", line(5, 5))] * MIN_GROUP
    final = [obs("1", line(3, 3), final=True)]
    (m, f) = fit_templates(medial + final)
    assert (m.final, f.final) == (False, True)
    assert m.knots == (5.0,) * 5
    assert f.n == MIN_GROUP + 1  # pooled
    # With enough final syllables the place has its own.
    (_, f) = fit_templates(medial + final * MIN_GROUP)
    assert f.knots == (3.0,) * 5 and f.n == MIN_GROUP


def test_spreads_are_the_scores_maximum_likelihood_sigmas():
    t = [Template("1", False, (5.0,) * 5, 4)]
    # Contours 0.5 above and below the template, so every residual is 0.5.
    o = [obs("1", line(5.5, 5.5)), obs("1", line(4.5, 4.5))] * 5
    s = fit_spread(o, t)
    assert s == Spread(contour=0.5, onset=round(math.sqrt(0.5 * 0.25), 3), offset=round(math.sqrt(0.5 * 0.25), 3), n=10)
    # The worst tenth is left out: one wild syllable among ten does not move them.
    wild = o[:9] + [obs("1", line(0, 0))]
    assert fit_spread(wild, t).contour == pytest.approx(0.5, abs=1e-3)
    assert fit_spread([], t) is None


def test_expand_matches_the_packs_linear_knots():
    assert np.allclose(expand([2, 1, 4]), [2, 1.78, 1.56, 1.33, 1.11, 1.33, 2, 2.67, 3.33, 4], atol=0.01)


SEED = (PACKS / "cmn.toml").read_text(encoding="utf-8")


def test_the_fitted_pack_replaces_the_full_tone_place_rules_and_the_spreads():
    templates = [Template("4", False, (4.5, 4.2, 4.0, 3.8, 3.6), 10), Template("3", True, (2.0,) * 5, 8)]
    pack = fitted_pack(SEED, templates, Spread(0.6, 0.5, 0.45, 18))
    standard = next(a for a in pack["accent"] if a["id"] == "cmn-standard")
    labels = [r["label"] for r in standard["realize"]]
    # The seed's t3-half and t3-final-dip are replaced; the neutral tone's rules stay.
    assert labels[:2] == ["t4-medial", "t3-final"]
    assert "t3-half" not in labels and "t3-final-dip" not in labels
    assert "t5-after-1" in labels and "t5-default" in labels
    assert standard["realize"][0] == {
        "label": "t4-medial",
        "when": {"tone": "4", "phrase_final": False},
        "chao": [4.5, 4.2, 4.0, 3.8, 3.6],
    }
    assert pack["tolerance"] == {"contour": 0.6, "onset": 0.5, "offset": 0.45, "turning_point": 0.2}
    # Taiwan keeps its own tone 3 and tolerance.
    tw = next(a for a in pack["accent"] if a["id"] == "cmn-TW")
    assert [r["label"] for r in tw["realize"]] == ["t3-low"] and tw["tolerance"] == {"contour": 0.8}


def test_the_rendered_pack_reads_back_and_tonekit_loads_it():
    templates = [Template(t, f, (3.0, 3.5, 4.0, 4.5, 5.0), 10) for t in "1234" for f in (False, True)]
    pack = fitted_pack(SEED, templates, Spread(0.6, 0.5, 0.45, 80))
    text = render(pack, "fitted by a test\n\nsecond line")
    assert text.startswith("# fitted by a test\n#\n# second line\n")
    assert tomllib.loads(text) == pack
    # tonekit validates every context of the pack when it loads it.
    grading = '{"accent": "cmn-standard", "style": null, "style_weight": 0.0}'
    tonekit_py.lattice(tonekit_py.analyze([0.0] * 1600, 16000), text, None, grading)


def test_the_seed_expectations_are_the_base_accents_rules_or_the_citation():
    seed = seed_expectations(SEED)
    assert set(seed) == {(t, f) for t in "1234" for f in (False, True)}
    assert np.allclose(seed[("4", False)], expand([5, 1]))  # no rule: the citation
    assert np.allclose(seed[("1", True)], expand([5, 5]))
    # A mixture's components averaged by weight: t3-half and t3-final-dip.
    assert np.allclose(seed[("3", False)], 0.75 * expand([2, 1]) + 0.25 * expand([2, 1, 4]))
    assert np.allclose(seed[("3", True)], 0.6 * expand([2, 1, 4]) + 0.4 * expand([2, 1]))


def test_shrinkage_pulls_the_median_towards_the_prior_by_strength():
    falls = [obs("4", line(5, 3))] * MIN_GROUP
    prior = {("4", False): line(5, 1), ("4", True): line(5, 1)}
    (alone,) = [t for t in fit_templates(falls) if not t.final]
    (half,) = [t for t in fit_templates(falls, prior, float(MIN_GROUP)) if not t.final]
    assert alone.knots[-1] == 3.0
    assert half.knots[-1] == 2.0  # κ = n: halfway between the median (3) and the prior (1)
    assert fit_templates(falls, prior, 0.0) == fit_templates(falls)
