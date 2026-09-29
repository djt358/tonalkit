//! An individual's realisation within an accent (imprint). No timbre, no embedding.

use serde::{Deserialize, Serialize};

use crate::ids::{AccentId, ToneId};

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct StyleTone {
    pub tone: ToneId,
    pub contour: Vec<f32>,
    pub n: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[cfg_attr(feature = "ffi", derive(uniffi::Record))]
pub struct StyleProfile {
    pub accent: AccentId,
    pub tones: Vec<StyleTone>,
    /// Chao units.
    pub mean_range: f32,
}
