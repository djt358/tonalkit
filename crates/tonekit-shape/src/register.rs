//! Speaker register: cold start from one utterance, and the running merge (spec §11.3).

use tonekit_core::Register;

use crate::chao::hz_to_st;

/// A register is cold until it has seen this many syllables.
const WARM_SYLLABLES: u32 = 30;
/// Cold start widens the observed p5..p95 by this much on each side.
const COLD_MARGIN_ST: f64 = 2.0;
/// The floor-to-ceiling distance never goes below this.
const MIN_SPAN_ST: f32 = 4.0;
/// One utterance never moves the register by more than this fraction of the way.
const MAX_MERGE_WEIGHT: f64 = 0.5;
/// What a register is when there is nothing to estimate it from (Hz).
const FALLBACK_HZ: (f32, f32, f32) = (90.0, 150.0, 250.0);

/// Percentile `p` (0..=1) of an ascending, non-empty slice, interpolating linearly between the
/// closest ranks (numpy's default).
fn percentile(sorted: &[f64], p: f64) -> f64 {
    let rank = p * (sorted.len() - 1) as f64;
    let lo = rank.floor() as usize;
    let hi = (lo + 1).min(sorted.len() - 1);
    sorted[lo] + (rank - lo as f64) * (sorted[hi] - sorted[lo])
}

/// The 5th, 50th and 95th percentiles of the finite values, or `None` if there are none.
fn p5_p50_p95(voiced_st: &[f32]) -> Option<(f64, f64, f64)> {
    let mut v: Vec<f64> = voiced_st
        .iter()
        .copied()
        .filter(|x| x.is_finite())
        .map(f64::from)
        .collect();
    if v.is_empty() {
        return None;
    }
    v.sort_by(f64::total_cmp);
    Some((
        percentile(&v, 0.05),
        percentile(&v, 0.5),
        percentile(&v, 0.95),
    ))
}

/// Widens the register symmetrically about its midpoint if it is narrower than 4 st.
///
/// The result is at least 4 st wide as `f32` subtraction sees it: rounding the two ends to `f32`
/// separately can leave the gap an ulp short of 4, so the ends are pushed apart a step at a time
/// until it is not.
fn at_least_min_span(mut r: Register) -> Register {
    if r.ceil_st - r.floor_st >= MIN_SPAN_ST {
        return r;
    }
    let mid = 0.5 * (f64::from(r.floor_st) + f64::from(r.ceil_st));
    let half = f64::from(MIN_SPAN_ST) / 2.0;
    r.floor_st = (mid - half) as f32;
    r.ceil_st = (mid + half) as f32;
    // An ulp of x is at most |x|·EPSILON, so this step is never lost to rounding and each pass
    // widens the gap. (A register that is not a number never satisfies the comparison: it is
    // left as it is.)
    let step = ((mid.abs() + half) as f32) * f32::EPSILON;
    while r.ceil_st - r.floor_st < MIN_SPAN_ST {
        r.floor_st -= step;
        r.ceil_st += step;
    }
    r
}

/// A register from one utterance's voiced semitones: p5 − 2 st, p50, p95 + 2 st, at least 4 st
/// wide, carrying `syllables` as its count.
///
/// With no voiced frames at all there is nothing to measure, so the result is the fixed
/// 90 / 150 / 250 Hz register with a count of 0.
pub fn cold_register(voiced_st: &[f32], syllables: u32) -> Register {
    match p5_p50_p95(voiced_st) {
        Some((p5, p50, p95)) => at_least_min_span(Register {
            floor_st: (p5 - COLD_MARGIN_ST) as f32,
            median_st: p50 as f32,
            ceil_st: (p95 + COLD_MARGIN_ST) as f32,
            n_syllables: syllables,
        }),
        None => Register {
            floor_st: hz_to_st(FALLBACK_HZ.0),
            median_st: hz_to_st(FALLBACK_HZ.1),
            ceil_st: hz_to_st(FALLBACK_HZ.2),
            n_syllables: 0,
        },
    }
}

/// Folds one utterance (`syllables` syllables, voiced semitones `voiced_st`) into a register:
/// each of floor, median and ceiling moves `w = min(0.5, u/(n+u))` of the way to the
/// utterance's p5, p50 and p95, where `n` is the register's count and `u` is `syllables`.
///
/// The result is at least 4 st wide. With no voiced frames only the count changes.
pub fn merge_register(r: &Register, voiced_st: &[f32], syllables: u32) -> Register {
    let n_syllables = r.n_syllables.saturating_add(syllables);
    let Some((p5, p50, p95)) = p5_p50_p95(voiced_st) else {
        return Register {
            n_syllables,
            ..r.clone()
        };
    };
    let total = f64::from(r.n_syllables) + f64::from(syllables);
    let w = if total > 0.0 {
        (f64::from(syllables) / total).min(MAX_MERGE_WEIGHT)
    } else {
        MAX_MERGE_WEIGHT
    };
    let toward = |old: f32, new: f64| (f64::from(old) + w * (new - f64::from(old))) as f32;
    at_least_min_span(Register {
        floor_st: toward(r.floor_st, p5),
        median_st: toward(r.median_st, p50),
        ceil_st: toward(r.ceil_st, p95),
        n_syllables,
    })
}

/// Whether the register has seen fewer than 30 syllables.
pub fn is_cold(r: &Register) -> bool {
    r.n_syllables < WARM_SYLLABLES
}
