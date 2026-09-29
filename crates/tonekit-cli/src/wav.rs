//! Reading the WAV: 16 kHz mono, PCM16 or 32-bit float, nothing else.

use std::path::Path;

use hound::{SampleFormat, WavReader, WavSpec};
use tonekit::SAMPLE_RATE;

use crate::CliError;

/// Full scale of a PCM16 sample.
const PCM16_SCALE: f32 = 32_768.0;

/// The samples of `path` as floats in `-1..1`.
///
/// A WAV in any other layout is a usage error (exit 2) whose message says how to convert it;
/// a file that cannot be read at all is a failure (exit 1).
pub fn read_mono_16k(path: &Path) -> Result<Vec<f32>, CliError> {
    let unreadable = |e: hound::Error| CliError::Failure(format!("{}: {e}", path.display()));
    let mut reader = WavReader::open(path).map_err(unreadable)?;
    let spec = reader.spec();
    if !is_supported(&spec) {
        return Err(CliError::Usage(format!(
            "{}: expected a 16 kHz mono WAV of 16-bit PCM or 32-bit float, got {}; \
             resample with `tkh ingest`",
            path.display(),
            describe(&spec)
        )));
    }
    match spec.sample_format {
        SampleFormat::Float => reader.samples::<f32>().collect::<Result<_, _>>(),
        SampleFormat::Int => reader
            .samples::<i16>()
            .map(|s| s.map(|x| f32::from(x) / PCM16_SCALE))
            .collect::<Result<_, _>>(),
    }
    .map_err(unreadable)
}

fn is_supported(spec: &WavSpec) -> bool {
    spec.channels == 1
        && spec.sample_rate == SAMPLE_RATE
        && matches!(
            (spec.sample_format, spec.bits_per_sample),
            (SampleFormat::Int, 16) | (SampleFormat::Float, 32)
        )
}

fn describe(spec: &WavSpec) -> String {
    let kind = match spec.sample_format {
        SampleFormat::Int => "PCM",
        SampleFormat::Float => "float",
    };
    format!(
        "{} Hz, {} channel(s), {}-bit {kind}",
        spec.sample_rate, spec.channels, spec.bits_per_sample
    )
}
