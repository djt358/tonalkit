//! Energy peaks with a vowel's spectrum and no pitch (ruling R102): syllables a pitch tracker lost.

use tonekit_core::F0Track;

use crate::runs::VOICING_RADIUS;
use crate::smooth::{local_extrema, Extremum};

/// A frame is vowel-like when at least this share of its energy above 150 Hz lies below 2 kHz
/// (`Analysis::sonority`). On the volunteer recordings the unpitched speech frames split into
/// fricatives and bursts under 0.2 and vowels over 0.5, and 95% of pitched frames read over 0.48
/// (front vowels in a high voice go down to about 0.3); white noise reads about 0.24.
pub const SONORANT_SHARE: f32 = 0.5;

/// The local maxima of the smoothed level `s` in `start..end` that are speech (`speech_at`), have
/// no pitch on any frame within [`VOICING_RADIUS`] (otherwise they are nucleus candidates, ruling
/// R27) and are vowel-like: the mean sonority of the frames within that radius is at least
/// [`SONORANT_SHARE`]. In frame order.
pub(crate) fn unpitched_peaks(
    s: &[f32],
    f0: &F0Track,
    sonority: &[f32],
    start: usize,
    end: usize,
    speech_at: impl Fn(usize) -> bool,
) -> Vec<usize> {
    let near =
        |at: usize| at.saturating_sub(VOICING_RADIUS)..(at + VOICING_RADIUS + 1).min(s.len());
    local_extrema(s, start, end, Extremum::Max)
        .into_iter()
        .filter(|&peak| {
            let around = near(peak);
            let pitched = around.clone().any(|i| f0.frames[i].hz.is_some());
            let mean = sonority[around.clone()].iter().sum::<f32>() / around.len() as f32;
            speech_at(peak) && !pitched && mean >= SONORANT_SHARE
        })
        .collect()
}
