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
    #[error("pack error: {message}")]
    Pack { message: String },
}
