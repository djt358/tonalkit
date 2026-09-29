//! Frame-level signal tracks. Frame indices are `u32` everywhere (UniFFI has no `usize` or tuples).

use serde::{Deserialize, Serialize};

/// Required input sample rate in Hz.
pub const SAMPLE_RATE: u32 = 16_000;
/// Samples per frame hop (10 ms at [`SAMPLE_RATE`]).
pub const HOP: usize = 160;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct F0Frame {
    pub hz: Option<f32>,
    pub voiced_p: f32,
}

/// Frame `i` is at `i * 10 ms`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct F0Track {
    pub frames: Vec<F0Frame>,
    pub provider: String,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct EnergyTrack {
    pub db: Vec<f32>,
}

/// Half-open frame interval `[start, end)`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct FrameRange {
    pub start: u32,
    pub end: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct Nucleus {
    pub frame: u32,
    pub strength_db: f32,
}
