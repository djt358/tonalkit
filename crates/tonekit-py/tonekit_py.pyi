"""Lexical-tone assessment: the tonekit Rust library for Python, JSON in and JSON out.

Every function takes and returns JSON text in the tonekit facade's serde format, so the numbers
are exactly the CLI's and the Swift package's. Failures raise ``ValueError`` with the library's
message (``TypeError`` for a ``pcm`` that is not audio or a ``sample_rate`` that is not an
integer).
"""

from collections.abc import Sequence

from _typeshed import ReadableBuffer

# 16 kHz mono float samples: a list or tuple of floats, or a one-dimensional native-byte-order
# float32 or float64 buffer (a numpy array, array.array, memoryview). Which buffers qualify is
# checked at run time (an int16 array or a two-dimensional one is refused).
Pcm = Sequence[float] | ReadableBuffer

def analyze(
    pcm: Pcm,
    sample_rate: int,
    register_json: str | None = None,
    f0_json: str | None = None,
) -> str:
    """Analyse one utterance (16 kHz mono floats in -1..1); returns the Analysis JSON.

    Raises ValueError for empty audio, audio longer than 30 seconds, a sample rate other than
    16000, or JSON that does not parse.
    """

def decode(
    analysis_json: str,
    pack_toml: str,
    calib_json: str | None,
    grading_json: str,
    candidates_json: str,
) -> str:
    """Score candidate readings against an analysis, best first; returns the DecodeResult JSON."""

def lattice(
    analysis_json: str,
    pack_toml: str,
    calib_json: str | None,
    grading_json: str,
) -> str:
    """The open-set tone lattice ("tonekit.lattice.v1"); returns the ToneLattice JSON."""

def assess(
    analysis_json: str,
    pack_toml: str,
    calib_json: str | None,
    request_json: str,
) -> str:
    """Grade an intended reading ("tonekit.assessment.v1"); returns the UtteranceAssessment JSON."""

def roll_register(
    previous_json: str | None,
    analysis_json: str,
    assessment_json: str,
    pack_toml: str,
    calib_json: str | None,
    params_json: str | None = None,
) -> str:
    """Roll a graded utterance into a speaker's register (R111); returns the RollingRegister JSON.

    Without params_json the pack calibration's rolling_register applies. Raises ValueError for
    unusable parameters, a bad pack, or JSON that does not parse.
    """

def roll_register_lite(
    previous_json: str | None,
    analysis_json: str,
    assessment_json: str,
    pack_toml: str,
    calib_json: str | None,
    params_json: str | None = None,
) -> str:
    """Roll a graded utterance into a four-number Register (R120); returns the Register JSON.

    previous_json is a Register (or None). Same half-life and cap as roll_register; without decay
    or cap it is register_update. Raises ValueError as roll_register does.
    """

def rolling_params(pack_toml: str, calib_json: str | None) -> str:
    """The pack calibration's rolling_register parameters (or tonekit's default) as JSON."""
