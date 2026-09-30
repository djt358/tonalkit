//! Identifier newtypes over `String`. Each serialises as the bare string.

use serde::{Deserialize, Serialize};

/// Language variety, ISO 639-3: `"cmn"`, `"yue"`.
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Lect(pub String);

/// Accent within a lect: `"cmn-standard"`, `"cmn-TW"`.
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct AccentId(pub String);

/// Tone identifier, scoped to a pack. cmn uses `"1"..="5"`, matching Bendy `Tone` raw values.
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ToneId(pub String);

/// Caller-chosen identifier for one candidate reading of an utterance.
#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct CandidateId(pub String);

// Swift sees each id as a plain `String` (a typealias), so callers write `ToneId` values as
// string literals; the wrapper types stay Rust-side.
#[cfg(feature = "ffi")]
mod ffi {
    use super::{AccentId, CandidateId, Lect, ToneId};

    uniffi::custom_newtype!(Lect, String);
    uniffi::custom_newtype!(AccentId, String);
    uniffi::custom_newtype!(ToneId, String);
    uniffi::custom_newtype!(CandidateId, String);
}
