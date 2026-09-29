//! `tonekit_py`: the tonekit facade for Python, JSON in and JSON out.
//!
//! The four functions mirror the Rust facade (`analyze`, `decode`, `lattice`, `assess`) and pass
//! everything else as JSON text in the facade's own serde format (spec §5), so a Python caller
//! gets exactly the numbers the CLI and the Swift package give: it is the same compiled code.
//! There are no Python-side mirror types to drift out of step.
//!
//! - Audio goes in as 16 kHz mono floats in -1..1: a list or tuple of floats, or a
//!   one-dimensional `float32`/`float64` buffer such as a numpy array.
//! - The language pack goes in as its TOML text and, optionally, its calibration JSON.
//! - Failures (an `AssessError`, a pack the library rejects, JSON that does not parse) raise
//!   `ValueError` with the error's message; a container that is not audio raises `TypeError`.
//!   Nothing panics across the boundary.
//! - The GIL is released while Rust computes, so Python threads can run alongside.

use std::ffi::CStr;

use pyo3::buffer::{ElementType, PyUntypedBuffer};
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use tonekit::{
    Analysis, AnalyzeOptions, AssessRequest, Candidate, F0Choice, F0Track, GradingTarget,
    LanguagePack, Register, SAMPLE_RATE,
};

/// Parses `$text` as a `$ty`; on failure the error names the Python argument (`$arg`).
///
/// A macro rather than a generic function so that this crate needs no `serde` dependency of its
/// own: the facade's types are `Deserialize`, and `serde_json` does the rest.
macro_rules! parse {
    ($ty:ty, $arg:literal, $text:expr) => {
        serde_json::from_str::<$ty>($text).map_err(|e| format!("invalid {}: {e}", $arg))
    };
}

/// Serialises a result to compact JSON.
macro_rules! emit {
    ($value:expr) => {
        serde_json::to_string(&$value).map_err(|e| format!("cannot serialise the result: {e}"))
    };
}

/// The library's failure text, as `ValueError` carries it.
fn failure(e: impl std::fmt::Display) -> String {
    e.to_string()
}

fn value_error(message: String) -> PyErr {
    PyValueError::new_err(message)
}

fn load_pack(pack_toml: &str, calib_json: Option<&str>) -> Result<LanguagePack, String> {
    LanguagePack::from_toml(pack_toml, calib_json).map_err(failure)
}

/// Whether a buffer `format` string has no byte-order character, or the native one that the
/// buffer protocol spells `@` or `=`. Byte order is decided here and not left to `PyBuffer`,
/// whose own check takes `>f` for native on little-endian hosts (pyo3 0.29): a big-endian numpy
/// array would then be read as garbage without a word.
fn is_native_order(format: &CStr) -> bool {
    matches!(format.to_bytes(), [_] | [b'@' | b'=', _])
}

/// The samples of `pcm` as `f32`, or the reason it is not audio.
///
/// A buffer (numpy array, `array.array`, `memoryview`) must be one-dimensional and hold native
/// `float32` or `float64`; anything else that is a sequence of numbers (a list, a tuple) is read
/// element by element. Integer buffers are refused rather than guessed at: the samples are floats
/// in -1..1, and int16 counts would be silently mis-scaled.
fn extract_pcm(pcm: &Bound<'_, PyAny>) -> PyResult<Vec<f32>> {
    const EXPECTED: &str = "pcm must be a one-dimensional float32 or float64 buffer (a numpy \
                            array, say) or a sequence of floats";
    let py = pcm.py();

    if let Ok(buffer) = PyUntypedBuffer::get(pcm) {
        if buffer.dimensions() != 1 {
            return Err(PyValueError::new_err(format!(
                "pcm must be one-dimensional (mono), got {} dimensions",
                buffer.dimensions()
            )));
        }
        let format = buffer.format().to_string_lossy().into_owned();
        if !is_native_order(buffer.format()) {
            return Err(PyTypeError::new_err(format!(
                "{EXPECTED}; this buffer (format {format:?}) is not in native byte order, so \
                 convert it first (numpy: `samples.astype(numpy.float32)`)"
            )));
        }
        let unusable = |why: PyErr| PyTypeError::new_err(format!("{EXPECTED} ({why})"));
        return match ElementType::from_format(buffer.format()) {
            ElementType::Float { bytes: 4 } => buffer
                .into_typed::<f32>()
                .and_then(|samples| samples.to_vec(py))
                .map_err(unusable),
            ElementType::Float { bytes: 8 } => buffer
                .into_typed::<f64>()
                .and_then(|samples| samples.to_vec(py))
                // Narrowing to the f32 the pipeline works in is the point of this arm.
                .map(|samples| samples.into_iter().map(|x| x as f32).collect())
                .map_err(unusable),
            _ => Err(PyTypeError::new_err(format!(
                "{EXPECTED}, not a buffer of format {format:?}"
            ))),
        };
    }

    pcm.extract::<Vec<f32>>()
        .map_err(|e| PyTypeError::new_err(format!("{EXPECTED} ({e})")))
}

fn analyze_json(
    pcm: &[f32],
    sample_rate: i64,
    register_json: Option<&str>,
    f0_json: Option<&str>,
) -> Result<String, String> {
    let register = register_json
        .map(|text| parse!(Register, "register_json", text))
        .transpose()?;
    let options = AnalyzeOptions {
        f0: match f0_json {
            Some(text) => F0Choice::External(parse!(F0Track, "f0_json", text)?),
            None => F0Choice::Pyin,
        },
    };
    // The library itself only knows u32 rates; anything outside that range is wrong the same way.
    let sample_rate = u32::try_from(sample_rate).map_err(|_| {
        format!("unsupported sample rate {sample_rate} Hz (expected {SAMPLE_RATE} Hz)")
    })?;
    let analysis =
        tonekit::analyze(pcm, sample_rate, register.as_ref(), &options).map_err(failure)?;
    emit!(analysis)
}

fn decode_json(
    analysis_json: &str,
    pack_toml: &str,
    calib_json: Option<&str>,
    grading_json: &str,
    candidates_json: &str,
) -> Result<String, String> {
    let analysis = parse!(Analysis, "analysis_json", analysis_json)?;
    let grading = parse!(GradingTarget, "grading_json", grading_json)?;
    let candidates = parse!(Vec<Candidate>, "candidates_json", candidates_json)?;
    let pack = load_pack(pack_toml, calib_json)?;
    let decoded = tonekit::decode(&analysis, &pack, &grading, &candidates).map_err(failure)?;
    emit!(decoded)
}

fn lattice_json(
    analysis_json: &str,
    pack_toml: &str,
    calib_json: Option<&str>,
    grading_json: &str,
) -> Result<String, String> {
    let analysis = parse!(Analysis, "analysis_json", analysis_json)?;
    let grading = parse!(GradingTarget, "grading_json", grading_json)?;
    let pack = load_pack(pack_toml, calib_json)?;
    let lattice = tonekit::lattice(&analysis, &pack, &grading).map_err(failure)?;
    emit!(lattice)
}

fn assess_json(
    analysis_json: &str,
    pack_toml: &str,
    calib_json: Option<&str>,
    request_json: &str,
) -> Result<String, String> {
    let analysis = parse!(Analysis, "analysis_json", analysis_json)?;
    let request = parse!(AssessRequest, "request_json", request_json)?;
    let pack = load_pack(pack_toml, calib_json)?;
    let assessment = tonekit::assess(&analysis, &pack, &request).map_err(failure)?;
    emit!(assessment)
}

/// Analyses one utterance, once, for any number of `decode`, `lattice` and `assess` calls.
///
/// `pcm` is 16 kHz mono audio as floats in -1..1: a list or tuple of floats, or a
/// one-dimensional float32 or float64 buffer (a numpy array). `sample_rate` must be 16000; the
/// caller resamples. `register_json` is the speaker's stored register (a `Register` object,
/// `{"floor_st": .., "median_st": .., "ceil_st": .., "n_syllables": ..}`); without it the
/// utterance's own cold-start register is used. `f0_json` is an `F0Track` computed elsewhere
/// (`{"frames": [{"hz": 123.4 or null, "voiced_p": 0.9}, ..], "provider": ".."}`, one frame per
/// 10 ms), used instead of the built-in pYIN tracker.
///
/// Returns the `Analysis` as JSON.
///
/// Raises `ValueError` for empty audio, a sample rate other than 16000 or JSON that does not
/// parse, and `TypeError` if `pcm` is not a sequence or buffer of floats.
#[pyfunction]
#[pyo3(signature = (pcm, sample_rate, register_json=None, f0_json=None))]
fn analyze(
    py: Python<'_>,
    pcm: &Bound<'_, PyAny>,
    sample_rate: i64,
    register_json: Option<&str>,
    f0_json: Option<&str>,
) -> PyResult<String> {
    let pcm = extract_pcm(pcm)?;
    py.detach(|| analyze_json(&pcm, sample_rate, register_json, f0_json))
        .map_err(value_error)
}

/// Scores candidate readings of any syllable count against an analysis, best first (closed set).
///
/// `analysis_json` is what `analyze` returned. `pack_toml` is the language pack's TOML and
/// `calib_json` its calibration JSON, or `None` for the pack's own seeds. `grading_json` is a
/// `GradingTarget` (`{"accent": "cmn-standard", "style": null, "style_weight": 0.0}`) and
/// `candidates_json` a JSON list of `Candidate` objects.
///
/// Returns the `DecodeResult` as JSON. Raises `ValueError` for anything the library rejects
/// (an unknown tone or accent, duplicate candidate ids, a bad pack) or JSON that does not parse.
#[pyfunction]
#[pyo3(signature = (analysis_json, pack_toml, calib_json, grading_json, candidates_json))]
fn decode(
    py: Python<'_>,
    analysis_json: &str,
    pack_toml: &str,
    calib_json: Option<&str>,
    grading_json: &str,
    candidates_json: &str,
) -> PyResult<String> {
    py.detach(|| {
        decode_json(
            analysis_json,
            pack_toml,
            calib_json,
            grading_json,
            candidates_json,
        )
    })
    .map_err(value_error)
}

/// The open-set tone lattice: per-syllable likelihoods over the pack's tone inventory, with no
/// candidates at all.
///
/// Arguments as for `decode`, without the candidates. Returns the `ToneLattice` as JSON (schema
/// `"tonekit.lattice.v1"`). Raises `ValueError` as `decode` does.
#[pyfunction]
#[pyo3(signature = (analysis_json, pack_toml, calib_json, grading_json))]
fn lattice(
    py: Python<'_>,
    analysis_json: &str,
    pack_toml: &str,
    calib_json: Option<&str>,
    grading_json: &str,
) -> PyResult<String> {
    py.detach(|| lattice_json(analysis_json, pack_toml, calib_json, grading_json))
        .map_err(value_error)
}

/// Grades an intended reading against an analysis.
///
/// `request_json` is an `AssessRequest`: `grading` and `intended` are required; `distractors`,
/// `external` and `compare_accents` default to empty. The other arguments are as for `decode`.
///
/// Returns the `UtteranceAssessment` as JSON (schema `"tonekit.assessment.v1"`). Raises
/// `ValueError` for anything the library rejects (an unknown tone or accent, duplicate candidate
/// ids, evidence of the wrong length, a bad pack) or JSON that does not parse.
#[pyfunction]
#[pyo3(signature = (analysis_json, pack_toml, calib_json, request_json))]
fn assess(
    py: Python<'_>,
    analysis_json: &str,
    pack_toml: &str,
    calib_json: Option<&str>,
    request_json: &str,
) -> PyResult<String> {
    py.detach(|| assess_json(analysis_json, pack_toml, calib_json, request_json))
        .map_err(value_error)
}

/// Lexical-tone assessment: the tonekit Rust library for Python, JSON in and JSON out.
#[pymodule]
fn tonekit_py(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(analyze, m)?)?;
    m.add_function(wrap_pyfunction!(decode, m)?)?;
    m.add_function(wrap_pyfunction!(lattice, m)?)?;
    m.add_function(wrap_pyfunction!(assess, m)?)?;
    Ok(())
}
