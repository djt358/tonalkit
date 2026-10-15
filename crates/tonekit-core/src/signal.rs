//! Frame-level signal tracks. Frame indices are `u32` everywhere (UniFFI has no `usize` or tuples).

use serde::{Deserialize, Serialize};

/// Required input sample rate in Hz.
pub const SAMPLE_RATE: u32 = 16_000;
/// Samples per frame hop (10 ms at [`SAMPLE_RATE`]).
pub const HOP: usize = 160;
/// A voiced run (a maximal stretch of frames with a pitch) bridges unvoiced gaps of at most this
/// many frames (ruling R32). Octave repair works run by run, and a nucleus's tone shape is taken
/// from its own run (ruling R50).
pub const MAX_BRIDGED_GAP_FRAMES: usize = 2;
/// A voiced run with fewer voiced frames than this is a short run (rulings R32, R35): octave
/// repair leaves it alone, and it never holds a nucleus of its own.
pub const MIN_RUN_FRAMES: usize = 5;

/// The voiced runs of `frames`, the indices of voiced frames in increasing order: consecutive
/// indices more than [`MAX_BRIDGED_GAP_FRAMES`] + 1 apart (more than that many unvoiced frames
/// between them) start a new run. Each run is returned as the range of positions in `frames` it
/// covers; together they cover `frames` in order. The one definition of a voiced run (ruling R32)
/// shared by octave repair, nucleus detection and shape extraction.
pub fn voiced_runs(frames: &[usize]) -> Vec<std::ops::Range<usize>> {
    let mut runs = Vec::new();
    let mut start = 0;
    for end in 1..=frames.len() {
        if end == frames.len() || frames[end] - frames[end - 1] > MAX_BRIDGED_GAP_FRAMES + 1 {
            runs.push(start..end);
            start = end;
        }
    }
    runs
}

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runs_bridge_gaps_of_up_to_two_frames() {
        assert_eq!(voiced_runs(&[]), Vec::<std::ops::Range<usize>>::new());
        assert_eq!(voiced_runs(&[7]), vec![0..1]);
        // 3 -> 6 skips two frames (bridged); 6 -> 10 skips three (a new run).
        assert_eq!(
            voiced_runs(&[1, 2, 3, 6, 10, 11, 20]),
            vec![0..4, 4..6, 6..7]
        );
    }
}
