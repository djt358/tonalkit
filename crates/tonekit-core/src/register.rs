//! Speaker pitch register.

use serde::{Deserialize, Serialize};

/// Semitones re 55 Hz. Four numbers, deliberately coarse (spec §11.3).
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Register {
    pub floor_st: f32,
    pub median_st: f32,
    pub ceil_st: f32,
    pub n_syllables: u32,
}
