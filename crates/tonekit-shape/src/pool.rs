//! The rolling register's pool (ruling R111): a fixed grid of semitone bins holding seconds of
//! voiced speech, and weighted percentiles over it.

use tonekit_core::{POOL_BINS, POOL_BIN_ST, POOL_LO_ST};

/// The bin a pitch (semitones re 55 Hz, finite) falls in; a pitch off the grid counts in the
/// nearest end bin.
pub(crate) fn bin_of(st: f32) -> usize {
    let at = ((f64::from(st) - f64::from(POOL_LO_ST)) / f64::from(POOL_BIN_ST)).floor();
    // `as` saturates: a negative position is bin 0.
    (at as usize).min(POOL_BINS - 1)
}

/// The weighted percentile `p` (0..=1) of a pool with positive `total` weight, reading each bin's
/// weight as spread evenly across it.
pub(crate) fn weighted_percentile(pool: &[f64], total: f64, p: f64) -> f64 {
    let lo = f64::from(POOL_LO_ST);
    let width = f64::from(POOL_BIN_ST);
    let target = p * total;
    let mut below = 0.0;
    let mut last = 0;
    for (i, &w) in pool.iter().enumerate() {
        if w <= 0.0 {
            continue;
        }
        last = i;
        if below + w >= target {
            let within = ((target - below) / w).clamp(0.0, 1.0);
            return lo + (i as f64 + within) * width;
        }
        below += w;
    }
    // Rounding can leave the target a hair above the sum of the bins: the top of the last one.
    lo + (last + 1) as f64 * width
}
