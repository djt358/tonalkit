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
