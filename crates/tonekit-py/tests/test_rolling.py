"""`tonekit_py.roll_register`, `tonekit_py.roll_register_lite` and `tonekit_py.rolling_params`
(rulings R111, R120): the rolling register and its four-number form in JSON, as Rust and Swift see
them."""

from __future__ import annotations

import json
import math

import pytest
import tonekit_py

from support import RATE, request_413

POOL_BINS = 540
POOLED = json.dumps({"half_life_s": None, "max_share": None})


@pytest.fixture(scope="module")
def graded(pcm, pack_toml, calib_json) -> tuple[str, str]:
    """The fixture's cold analysis and its assessment, as JSON."""
    analysis = tonekit_py.analyze(pcm, RATE)
    assessment = tonekit_py.assess(analysis, pack_toml, calib_json, json.dumps(request_413()))
    return analysis, assessment


def test_a_cold_start_rolls_into_a_register_and_a_pool(graded, pack_toml, calib_json):
    analysis, assessment = graded
    rolled = json.loads(tonekit_py.roll_register(None, analysis, assessment, pack_toml, calib_json))
    assert set(rolled) == {"register", "pool"}
    assert rolled["register"]["n_syllables"] == 3
    assert len(rolled["pool"]) == POOL_BINS
    # 0.01 s per speech-only voiced frame, at most the default cap of about 1.32 s.
    voiced_s = 0.01 * len(json.loads(analysis)["voiced_st"])
    assert sum(rolled["pool"]) == pytest.approx(min(voiced_s, 1.3183), abs=1e-3)


def test_the_register_goes_back_into_analyze_and_the_whole_value_into_the_next_roll(
    pcm, graded, pack_toml, calib_json
):
    analysis, assessment = graded
    first = tonekit_py.roll_register(None, analysis, assessment, pack_toml, calib_json)
    register = json.dumps(json.loads(first)["register"])
    warm = tonekit_py.analyze(pcm, RATE, register)
    assert json.loads(warm)["register_source"] == "Given"
    again = tonekit_py.assess(warm, pack_toml, calib_json, json.dumps(request_413()))
    second = json.loads(tonekit_py.roll_register(first, warm, again, pack_toml, calib_json))
    assert second["register"]["n_syllables"] == 6


def test_parameters_come_from_the_calibration_unless_given(graded, pack_toml, calib_json):
    analysis, assessment = graded
    assert json.loads(tonekit_py.rolling_params(pack_toml, calib_json)) == {"half_life_s": 30.0, "max_share": 0.03}
    assert json.loads(tonekit_py.rolling_params(pack_toml, None)) == {"half_life_s": 30.0, "max_share": 0.03}
    calib = json.loads(calib_json)
    calib["rolling_register"] = {"half_life_s": 5.0, "max_share": 0.5}
    tuned = json.dumps(calib)
    assert json.loads(tonekit_py.rolling_params(pack_toml, tuned)) == {"half_life_s": 5.0, "max_share": 0.5}
    # A bigger cap lets the whole utterance in; POOLED takes every frame, whatever the pack says.
    frames = 0.01 * len(json.loads(analysis)["voiced_st"])
    by_pack = json.loads(tonekit_py.roll_register(None, analysis, assessment, pack_toml, tuned))
    pooled = json.loads(tonekit_py.roll_register(None, analysis, assessment, pack_toml, tuned, POOLED))
    assert sum(by_pack["pool"]) == pytest.approx(min(frames, -5.0 * math.log2(0.5)), abs=1e-6)
    assert sum(pooled["pool"]) == pytest.approx(frames, abs=1e-6)


def test_bad_parameters_and_bad_json_are_value_errors(graded, pack_toml, calib_json):
    analysis, assessment = graded
    with pytest.raises(ValueError, match="rolling register parameters: half_life_s"):
        tonekit_py.roll_register(
            None, analysis, assessment, pack_toml, calib_json, json.dumps({"half_life_s": 0, "max_share": None})
        )
    with pytest.raises(ValueError, match="invalid previous_json"):
        tonekit_py.roll_register("{}", analysis, assessment, pack_toml, calib_json)
    with pytest.raises(ValueError, match="invalid assessment_json"):
        tonekit_py.roll_register(None, analysis, "[]", pack_toml, calib_json)
    calib = json.loads(calib_json)
    calib["rolling_register"] = {"half_life_s": 30.0}
    with pytest.raises(ValueError, match="max_share"):
        tonekit_py.rolling_params(pack_toml, json.dumps(calib))


def test_the_lite_register_is_four_numbers_and_without_decay_is_register_update(
    pcm, graded, pack_toml, calib_json
):
    analysis, assessment = graded
    first = tonekit_py.roll_register_lite(None, analysis, assessment, pack_toml, calib_json)
    assert set(json.loads(first)) == {"floor_st", "median_st", "ceil_st", "n_syllables"}
    assert json.loads(first) == json.loads(assessment)["register_update"]  # the cold start
    warm = tonekit_py.analyze(pcm, RATE, first)
    again = tonekit_py.assess(warm, pack_toml, calib_json, json.dumps(request_413()))
    second = json.loads(tonekit_py.roll_register_lite(first, warm, again, pack_toml, calib_json))
    assert second["n_syllables"] == 6
    pooled = tonekit_py.roll_register_lite(first, warm, again, pack_toml, calib_json, POOLED)
    assert json.loads(pooled) == json.loads(again)["register_update"]
    with pytest.raises(ValueError, match="invalid previous_json"):
        tonekit_py.roll_register_lite("{}", analysis, assessment, pack_toml, calib_json)
    with pytest.raises(ValueError, match="rolling register parameters: max_share"):
        tonekit_py.roll_register_lite(
            None, analysis, assessment, pack_toml, calib_json, json.dumps({"half_life_s": None, "max_share": 0.1})
        )
