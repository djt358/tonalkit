//! Errors returned by the tonekit pipeline.

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::ids::{CandidateId, ToneId};
use crate::signal::SAMPLE_RATE;

#[derive(Clone, Debug, PartialEq, Error, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Error))]
pub enum AssessError {
    #[error("audio is empty")]
    EmptyAudio,
    #[error("unsupported sample rate {got} Hz (expected {} Hz)", SAMPLE_RATE)]
    UnsupportedSampleRate { got: u32 },
    #[error("unknown tone {tone:?}")]
    UnknownTone { tone: ToneId },
    #[error("duplicate candidate id {id:?}")]
    DuplicateCandidate { id: CandidateId },
    #[error("evidence length mismatch: expected {expected} syllables, got {got}")]
    EvidenceLengthMismatch { expected: u32, got: u32 },
    /// A pack that cannot be loaded or used as asked (an unknown accent, bad variant weights, a
    /// malformed pack or calibration).
    #[error("pack error: {message}")]
    Pack { message: String },
    /// A request that cannot be graded whatever the audio: no candidates, a candidate with no
    /// targets, an intended candidate the decode does not hold.
    #[error("invalid request: {message}")]
    InvalidRequest { message: String },
    /// Audio longer than `max` seconds (ruling R52: the dense pYIN is unbounded in memory).
    #[error("audio is {seconds} s long; at most {max} s can be assessed")]
    TooLong { seconds: f32, max: f32 },
}
