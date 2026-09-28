//! Errors from loading a pack or resolving an expectation.

use thiserror::Error;
use tonekit_core::{AccentId, ToneId};

#[derive(Clone, Debug, PartialEq, Error)]
pub enum PackError {
    /// The pack TOML or the calibration JSON is not well-formed, or has a wrong or unknown field.
    #[error("pack parse error: {0}")]
    Parse(String),
    /// Well-formed but breaks a schema rule (unknown capability, weights that do not sum to 1,
    /// dangling reference, cycle, out-of-range value, ...).
    #[error("invalid pack: {0}")]
    Invalid(String),
    /// A tone whose citation is `"context"` has no `realize` rule for this context.
    #[error("tone {tone:?} has no realisation for {context}")]
    MissingRealization { tone: ToneId, context: String },
    #[error("unknown accent {0:?}")]
    UnknownAccent(AccentId),
    #[error("unknown tone {0:?}")]
    UnknownTone(ToneId),
}

pub(crate) fn invalid<T>(msg: impl Into<String>) -> Result<T, PackError> {
    Err(PackError::Invalid(msg.into()))
}
