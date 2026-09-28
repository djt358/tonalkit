//! Semitone and Chao conversions, and the definition of a voiced frame.

use tonekit_core::{F0Frame, F0Track, FrameRange, Register};

/// Semitones are measured re this frequency.
const REF_HZ: f64 = 55.0;
/// A frame is voiced when it has an f0 and `voiced_p` is at least this.
const VOICED_P_MIN: f32 = 0.5;
/// Register width used by [`st_to_chao`] when the register has no usable width.
const FALLBACK_SPAN_ST: f64 = 4.0;

pub(crate) fn hz_to_st_f64(hz: f64) -> f64 {
    12.0 * (hz / REF_HZ).log2()
}

/// Semitones re 55 Hz: `12·log2(hz/55)`.
pub fn hz_to_st(hz: f32) -> f32 {
    hz_to_st_f64(f64::from(hz)) as f32
}

/// Chao value of `st` in the register: `1 + 4·(st − floor)/(ceil − floor)`, unclamped.
///
/// A register whose width is not a positive number (which the register functions never produce,
/// but a caller can) is read as 4 st wide from its floor, so the result is always finite.
pub(crate) fn st_to_chao_f64(st: f64, r: &Register) -> f64 {
    let floor = f64::from(r.floor_st);
    let width = f64::from(r.ceil_st) - floor;
    let width = if width.is_finite() && width > 0.0 {
        width
    } else {
        FALLBACK_SPAN_ST
    };
    1.0 + 4.0 * (st - floor) / width
}

/// Chao value of `st` in the register: `1 + 4·(st − floor)/(ceil − floor)`, unclamped.
pub fn st_to_chao(st: f32, r: &Register) -> f32 {
    st_to_chao_f64(f64::from(st), r) as f32
}

/// The semitone value (re 55 Hz) of a voiced frame: `hz.is_some() && voiced_p ≥ 0.5`.
///
/// An f0 that is not a positive finite number cannot be a pitch, so such a frame is not voiced
/// however confident it claims to be.
pub(crate) fn voiced_st(frame: &F0Frame) -> Option<f64> {
    let hz = frame.hz?;
    (hz.is_finite() && hz > 0.0 && frame.voiced_p >= VOICED_P_MIN)
        .then(|| hz_to_st_f64(f64::from(hz)))
}

/// Semitones (re 55 Hz) of the voiced frames of `f0`, in order, within the half-open
/// `[region.start, region.end)` if a region is given (clamped to the track).
pub fn voiced_semitones(f0: &F0Track, region: Option<&FrameRange>) -> Vec<f32> {
    let len = f0.frames.len();
    let (start, end) = match region {
        Some(r) => ((r.start as usize).min(len), (r.end as usize).min(len)),
        None => (0, len),
    };
    if start >= end {
        return Vec::new();
    }
    f0.frames[start..end]
        .iter()
        .filter_map(voiced_st)
        .map(|st| st as f32)
        .collect()
}
