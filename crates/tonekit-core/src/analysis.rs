//! The result of analysing one utterance once; decoding and grading query it many times.

use serde::{Deserialize, Serialize};

use crate::judgement::MeasureIssue;
use crate::register::Register;
use crate::signal::{EnergyTrack, F0Track, FrameRange, Nucleus};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Enum))]
pub enum RegisterSource {
    Given,
    ColdStart,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct Analysis {
    pub f0: F0Track,
    pub energy: EnergyTrack,
    pub nuclei: Vec<Nucleus>,
    pub boundaries: Vec<u32>,
    pub speech: Option<FrameRange>,
    pub register: Register,
    pub register_source: RegisterSource,
    pub voiced_st: Vec<f32>,
    pub issues: Vec<MeasureIssue>,
}
