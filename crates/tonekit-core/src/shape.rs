//! Tone-bearing-unit shape features.

use serde::{Deserialize, Serialize};

/// Number of points in a normalised contour.
pub const CONTOUR_POINTS: usize = 10;

/// Half-open frame interval `[start, end)`.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct TbuSpan {
    pub start_frame: u32,
    pub end_frame: u32,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ToneShape {
    pub span: TbuSpan,
    /// Chao scale: 1 + 4·(st − floor)/(ceil − floor), unclamped; `CONTOUR_POINTS` long.
    pub contour: Vec<f32>,
    /// Per-point fraction of voiced frames behind each contour point (0..1).
    pub voiced_weights: Vec<f32>,
    pub onset: f32,
    pub offset: f32,
    pub mean: f32,
    pub slope: f32,
    pub curvature: f32,
    pub turning_point: Option<f32>,
    pub range: f32,
    pub duration_ms: f32,
    pub voiced_fraction: f32,
    pub f0_confidence: f32,
    /// Reserved; `None` until a pack declares it.
    pub phonation: Option<Phonation>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Phonation {
    pub creak_ratio: f32,
    pub cpp_db: f32,
}
