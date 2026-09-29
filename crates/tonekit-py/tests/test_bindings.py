"""The four JSON-in, JSON-out functions of `tonekit_py`: shapes, inputs, errors, threading."""

from __future__ import annotations

import array
import json
import threading
import time

import numpy as np
import pytest
import tonekit_py

from support import RATE, candidate, request_413, standard_grading
from test_parity import TOLERANCE, json_max_diff

CMN_TONES = ["1", "2", "3", "4", "5"]


@pytest.fixture(scope="module")
def analysis_json(pcm) -> str:
    return tonekit_py.analyze(pcm, RATE)


def assess_413(analysis_json, pack_toml, calib_json, request=None) -> dict:
    request = request_413() if request is None else request
    return json.loads(tonekit_py.assess(analysis_json, pack_toml, calib_json, json.dumps(request)))


# ---- analyze -------------------------------------------------------------------------------


def test_analyze_returns_the_analysis_json(pcm, analysis_json):
    analysis = json.loads(analysis_json)
    assert set(analysis) >= {
        "f0", "energy", "nuclei", "boundaries", "speech", "register", "register_source",
        "voiced_st", "issues",
    }  # fmt: skip
    # One frame per 10 ms at frame i * 160 samples: len(pcm) // 160 + 1 for every track.
    frames = len(pcm) // 160 + 1
    assert len(analysis["f0"]["frames"]) == frames
    assert len(analysis["energy"]["db"]) == frames
    assert analysis["f0"]["provider"] == "pyin"
    assert analysis["register_source"] == "ColdStart"
    assert "ColdStartRegister" in analysis["issues"]
    assert len(analysis["nuclei"]) == 3


def test_analyze_is_deterministic(pcm, analysis_json):
    assert tonekit_py.analyze(pcm, RATE) == analysis_json


def test_analyze_accepts_a_given_register(pcm):
    register = {"floor_st": 9.0, "median_st": 17.5, "ceil_st": 24.0, "n_syllables": 40}
    analysis = json.loads(tonekit_py.analyze(pcm, RATE, register_json=json.dumps(register)))
    assert analysis["register_source"] == "Given"
    assert analysis["register"] == register
    assert "ColdStartRegister" not in analysis["issues"]  # 40 syllables: no longer cold


def test_analyze_accepts_an_external_f0_track(pcm, analysis_json, pack_toml, calib_json):
    """Feeding the analysis's own f0 back as an External track grades the same (R43 sanitising
    is a no-op on a clean track), and reports the provider as "external"."""
    own = json.loads(analysis_json)
    again_json = tonekit_py.analyze(pcm, RATE, f0_json=json.dumps(own["f0"]))
    again = json.loads(again_json)
    assert again["f0"]["provider"] == "external"
    assert len(again["f0"]["frames"]) == len(own["f0"]["frames"])

    # The whole assessment, not a hand-picked subset: every number within 1e-4, everything else
    # (heard tones, deltas, components, register update, ...) identical.
    want = assess_413(analysis_json, pack_toml, calib_json)
    got = assess_413(again_json, pack_toml, calib_json)
    json_max_diff(want, got, TOLERANCE)


def test_an_external_f0_track_is_padded_to_the_frame_count(pcm):
    track = {"frames": [{"hz": 150.0, "voiced_p": 1.0}] * 10, "provider": "whatever"}
    analysis = json.loads(tonekit_py.analyze(pcm, RATE, f0_json=json.dumps(track)))
    assert len(analysis["f0"]["frames"]) == len(pcm) // 160 + 1
    assert analysis["f0"]["provider"] == "external"


@pytest.mark.parametrize(
    "make",
    [
        pytest.param(lambda a: a, id="float32 ndarray"),
        pytest.param(lambda a: a.astype(np.float64), id="float64 ndarray"),
        pytest.param(lambda a: a.tolist(), id="list of float"),
        pytest.param(lambda a: tuple(a.tolist()), id="tuple of float"),
        pytest.param(lambda a: array.array("f", a.tobytes()), id="array.array('f')"),
        pytest.param(lambda a: memoryview(a), id="memoryview"),
        pytest.param(lambda a: np.repeat(a, 2)[::2], id="strided (non-contiguous) view"),
    ],
)
def test_analyze_accepts_the_usual_sample_containers(pcm, analysis_json, make):
    assert tonekit_py.analyze(make(pcm), RATE) == analysis_json


def test_analyze_accepts_a_numpy_sample_rate(pcm, analysis_json):
    assert tonekit_py.analyze(pcm, np.int64(RATE)) == analysis_json


def test_analyze_rejects_things_that_are_not_mono_float_samples(pcm):
    with pytest.raises(ValueError, match="one-dimensional"):
        tonekit_py.analyze(np.zeros((2, 3200), dtype=np.float32), RATE)
    # int16 counts would be silently mis-scaled (the pcm is floats in -1..1), so refuse them.
    with pytest.raises(TypeError, match="pcm"):
        tonekit_py.analyze((pcm * 32767).astype(np.int16), RATE)
    with pytest.raises(TypeError, match="pcm"):
        tonekit_py.analyze(b"not audio", RATE)
    with pytest.raises(TypeError, match="pcm"):
        tonekit_py.analyze("not audio", RATE)
    with pytest.raises(TypeError, match="pcm"):
        tonekit_py.analyze(3.5, RATE)


def test_analyze_refuses_a_buffer_in_the_other_byte_order(pcm):
    """The pcm is read as native floats; an array in the other byte order (">f4" on a little-endian
    host) would be silently garbled, so it is refused."""
    swapped32 = pcm.astype(np.dtype(np.float32).newbyteorder("S"))
    assert not np.array_equal(swapped32.view(np.uint32), pcm.view(np.uint32))  # really swapped
    with pytest.raises(TypeError, match="byte order"):
        tonekit_py.analyze(swapped32, RATE)
    swapped64 = pcm.astype(np.dtype(np.float64).newbyteorder("S"))
    with pytest.raises(TypeError, match="byte order"):
        tonekit_py.analyze(swapped64, RATE)


@pytest.mark.parametrize(
    "samples",
    [
        pytest.param(np.zeros(16_000, dtype=np.float32), id="silence"),
        pytest.param(np.full(16_000, np.nan, dtype=np.float32), id="NaN samples"),
        pytest.param(np.full(16_000, np.inf, dtype=np.float32), id="infinite samples"),
        pytest.param(np.array([0.5], dtype=np.float32), id="a single sample"),
    ],
)
def test_audio_with_no_speech_is_analysed_not_rejected(samples, pack_toml, calib_json):
    """Nothing to measure is not an error: every syllable of the assessment is NotMeasured."""
    analysis_json = tonekit_py.analyze(samples, RATE)
    got = assess_413(analysis_json, pack_toml, calib_json)
    assert got["overall"] is None
    assert all("NotMeasured" in s["measured"] for s in got["syllables"])


# ---- errors are ValueError ------------------------------------------------------------------


def test_a_wrong_sample_rate_is_a_value_error(pcm):
    with pytest.raises(ValueError, match=r"unsupported sample rate 44100 Hz \(expected 16000 Hz\)"):
        tonekit_py.analyze(pcm, 44_100)


@pytest.mark.parametrize("rate", [2**70, -(2**70), 2**63, -(2**63) - 1, 2**32, -1])
def test_an_out_of_range_sample_rate_is_a_value_error(pcm, rate):
    """Including integers too large for 64 bits, which PyO3's own conversion would raise as
    OverflowError; the message names the valid range."""
    with pytest.raises(ValueError, match=rf"unsupported sample rate {rate} Hz \(expected 16000 Hz"):
        tonekit_py.analyze(pcm, rate)
    with pytest.raises(TypeError, match="sample_rate must be an integer"):
        tonekit_py.analyze(pcm, "16000")


def test_empty_audio_is_a_value_error():
    with pytest.raises(ValueError, match="audio is empty"):
        tonekit_py.analyze([], RATE)
    with pytest.raises(ValueError, match="audio is empty"):
        tonekit_py.analyze(np.zeros(0, dtype=np.float32), RATE)


def test_a_bad_pack_is_a_value_error(analysis_json, calib_json):
    request = json.dumps(request_413())
    with pytest.raises(ValueError, match="pack"):
        tonekit_py.assess(analysis_json, "this is [not toml", calib_json, request)
    with pytest.raises(ValueError, match="pack"):
        tonekit_py.lattice(
            analysis_json, "this is [not toml", calib_json, json.dumps(standard_grading())
        )
    with pytest.raises(ValueError, match="pack"):
        tonekit_py.decode(
            analysis_json,
            "",
            None,
            json.dumps(standard_grading()),
            json.dumps([candidate("a", ["1"])]),
        )


def test_a_bad_calibration_is_a_value_error(analysis_json, pack_toml):
    with pytest.raises(ValueError, match="calib"):
        tonekit_py.assess(analysis_json, pack_toml, "{not json", json.dumps(request_413()))


def test_assess_errors_carry_the_assess_error_text(analysis_json, pack_toml, calib_json):
    unknown_tone = request_413()
    unknown_tone["intended"] = candidate("intended", ["4", "9"])
    with pytest.raises(ValueError, match="unknown tone"):
        tonekit_py.assess(analysis_json, pack_toml, calib_json, json.dumps(unknown_tone))

    duplicate = request_413()
    duplicate["distractors"] = [candidate("intended", ["1", "1", "1"])]
    with pytest.raises(ValueError, match="duplicate candidate id"):
        tonekit_py.assess(analysis_json, pack_toml, calib_json, json.dumps(duplicate))

    evidence = request_413()
    evidence["external"] = [[]]  # one list, but three syllables
    with pytest.raises(ValueError, match="evidence length mismatch"):
        tonekit_py.assess(analysis_json, pack_toml, calib_json, json.dumps(evidence))

    accent = request_413()
    accent["grading"]["accent"] = "cmn-nowhere"
    with pytest.raises(ValueError, match="pack error"):
        tonekit_py.assess(analysis_json, pack_toml, calib_json, json.dumps(accent))


def test_malformed_json_is_a_value_error_that_names_the_argument(
    pcm, analysis_json, pack_toml, calib_json
):
    request = json.dumps(request_413())
    grading = json.dumps(standard_grading())
    with pytest.raises(ValueError, match="analysis_json"):
        tonekit_py.assess("{", pack_toml, calib_json, request)
    with pytest.raises(ValueError, match="analysis_json"):
        tonekit_py.lattice('{"f0": 1}', pack_toml, calib_json, grading)  # valid JSON, wrong shape
    with pytest.raises(ValueError, match="request_json"):
        tonekit_py.assess(analysis_json, pack_toml, calib_json, "[]")
    with pytest.raises(ValueError, match="grading_json"):
        tonekit_py.lattice(analysis_json, pack_toml, calib_json, "nope")
    with pytest.raises(ValueError, match="candidates_json"):
        tonekit_py.decode(analysis_json, pack_toml, calib_json, grading, '{"id": "a"}')
    with pytest.raises(ValueError, match="register_json"):
        tonekit_py.analyze(pcm, RATE, register_json="{}")
    with pytest.raises(ValueError, match="f0_json"):
        tonekit_py.analyze(pcm, RATE, f0_json="[1, 2]")


# ---- decode, lattice, assess ----------------------------------------------------------------


def test_decode_ranks_the_candidates(analysis_json, pack_toml, calib_json):
    candidates = [candidate("wrong", ["1", "4", "2"]), candidate("right", ["4", "1", "3"])]
    decoded = json.loads(
        tonekit_py.decode(
            analysis_json,
            pack_toml,
            calib_json,
            json.dumps(standard_grading()),
            json.dumps(candidates),
        )
    )
    ranked = decoded["candidates"]
    assert [c["id"] for c in ranked] == ["right", "wrong"]  # best first
    assert ranked[0]["llr"] > ranked[1]["llr"]
    assert len(ranked[0]["syllables"]) == 3


def test_lattice_is_the_open_set_tone_lattice(analysis_json, pack_toml, calib_json):
    lattice = json.loads(
        tonekit_py.lattice(analysis_json, pack_toml, calib_json, json.dumps(standard_grading()))
    )
    assert lattice["schema"] == "tonekit.lattice.v1"
    assert lattice["lect"] == "cmn"
    assert lattice["accent"] == "cmn-standard"
    assert lattice["inventory"] == CMN_TONES
    assert len(lattice["tbus"]) == 3
    for tbu in lattice["tbus"]:
        assert len(tbu["loglik"]) == len(tbu["posterior"]) == len(CMN_TONES)
        assert sum(tbu["posterior"]) == pytest.approx(1.0, abs=1e-4)


def test_the_calibration_is_optional(analysis_json, pack_toml):
    """No calibration means the pack's own seeds (None, like Pack.fromToml(calibJson: nil))."""
    grading = json.dumps(standard_grading())
    lattice = json.loads(tonekit_py.lattice(analysis_json, pack_toml, None, grading))
    assert lattice["schema"] == "tonekit.lattice.v1"
    decoded = json.loads(
        tonekit_py.decode(
            analysis_json, pack_toml, None, grading, json.dumps([candidate("a", ["4", "1", "3"])])
        )
    )
    assert decoded["candidates"][0]["id"] == "a"
    assessed = assess_413(analysis_json, pack_toml, None)
    assert assessed["schema"] == "tonekit.assessment.v1"
    assert assessed["intended_rank"] == 1


def test_a_request_needs_only_grading_and_intended(analysis_json, pack_toml, calib_json):
    """`distractors`, `external` and `compare_accents` default to empty (R39)."""
    minimal = {"grading": standard_grading(), "intended": request_413()["intended"]}
    got = assess_413(analysis_json, pack_toml, calib_json, minimal)
    want = assess_413(analysis_json, pack_toml, calib_json)
    assert got == want


def test_assess_with_distractors_and_compared_accents(analysis_json, pack_toml, calib_json):
    request = request_413()
    request["distractors"] = [candidate("d1", ["1", "4", "2"])]
    request["compare_accents"] = ["cmn-standard"]
    got = assess_413(analysis_json, pack_toml, calib_json, request)
    assert got["intended_rank"] == 1
    assert got["margin_llr"] > 0
    assert [fit["accent"] for fit in got["accent_fit"]] == ["cmn-standard"]


# ---- the GIL --------------------------------------------------------------------------------


# One `analyze` call must take at least this long for the GIL test to mean anything: a held GIL
# then lets the counting thread advance by at most one switch interval (5 ms), 5% of the call.
MIN_CALL_S = 0.1
MAX_COPIES = 64


def audio_for_a_measurable_call(pcm):
    """`pcm` repeated (doubling the copies) until one `analyze` call takes at least MIN_CALL_S.

    How long a call takes depends on the machine, so the workload is scaled to it instead of being
    fixed. Gives up (skipping the test) at MAX_COPIES, about 85 s of audio."""
    copies = 1
    while True:
        audio = np.tile(pcm, copies)
        start = time.perf_counter()
        tonekit_py.analyze(audio, RATE)
        if time.perf_counter() - start >= MIN_CALL_S:
            return audio
        if copies >= MAX_COPIES:
            pytest.skip(f"analyze of {copies} copies of the fixture takes under {MIN_CALL_S} s")
        copies *= 2


def test_the_gil_is_released_while_rust_computes(pcm):
    """A Python thread keeps counting while another thread is inside `analyze`. Measured against
    its own rate when idle: if the extension held the GIL for the whole call, the counter could
    advance only by the one switch interval (5 ms) after the call, at most 5% of a call of
    MIN_CALL_S; released, it keeps roughly its full rate."""
    audio = audio_for_a_measurable_call(pcm)
    counter = 0
    stop = threading.Event()

    def count():
        nonlocal counter
        while not stop.is_set():
            counter += 1

    thread = threading.Thread(target=count)
    thread.start()
    try:
        while counter == 0:  # the counting thread is running
            time.sleep(0.001)
        start_count, start_time = counter, time.perf_counter()
        time.sleep(0.2)
        idle_rate = (counter - start_count) / (time.perf_counter() - start_time)

        start_count, start_time = counter, time.perf_counter()
        tonekit_py.analyze(audio, RATE)
        duration = time.perf_counter() - start_time
        gained = counter - start_count
    finally:
        stop.set()
        thread.join()
    if duration <= MIN_CALL_S / 2:  # a faster machine or a warm cache: too short to judge
        pytest.skip(
            f"the measured analyze call took {duration:.3f} s (need > {MIN_CALL_S / 2:.3f} s); "
            f"the counter gained {gained} against an idle rate of {idle_rate:.0f}/s"
        )
    share = gained / (idle_rate * duration)
    assert share > 0.25, (
        f"the counting thread ran at {share:.1%} of its idle rate during analyze; "
        "the GIL is being held"
    )
