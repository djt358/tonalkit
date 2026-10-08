//! Rolling an utterance into a [`RollingRegister`] (ruling R111): decay the pool, cap the
//! utterance's weight, add its voiced frames and read the register off the pool.

use tonekit_core::{Register, RollingParams, RollingRegister, HOP, POOL_BINS, SAMPLE_RATE};

use crate::pool::{bin_of, weighted_percentile};
use crate::register::{at_least_min_span, fallback_register, COLD_MARGIN_ST, WARM_SYLLABLES};

/// Seconds of speech one voiced frame stands for.
const FRAME_S: f64 = HOP as f64 / SAMPLE_RATE as f64;
/// A bin that decays below this many seconds is emptied, which keeps a stored pool tidy.
const NEGLIGIBLE_S: f64 = 1e-6;

/// Rolls one utterance into `previous` (`None`: nothing yet, a cold start): `voiced_st` are its
/// speech-only voiced semitones (`Analysis::voiced_st`, ruling R106) and `syllables` how many of
/// its syllables were measured (ruling R38).
///
/// 1. With no syllable measured there is nothing to learn: `previous` comes back as it is (or an
///    empty register counting no syllables). A `previous` whose pool is not usable
///    ([`RollingRegister::pool_usable`]) is started afresh.
/// 2. The utterance counts as its voiced seconds (0.01 s a frame), at most
///    `−half_life_s · log2(1 − max_share)` seconds. The pool decays by `2^(−counted/half_life_s)`
///    (the clock runs on counted speech, so a capped utterance cannot flush the pool either),
///    then each frame adds `counted / frames` to its bin. Without voiced frames the pool stays.
/// 3. The register is the pool's weighted p5, p50 and p95, the floor and ceiling pushed out by
///    `2 st · (1 − min(n, 30)/30)` for `n` syllables (the cold start's margin, gone once the
///    register is warm), at least 4 st wide. A pool with no weight gives the fixed fallback
///    register counting no syllables.
///
/// `params` are assumed usable ([`RollingParams::problem`] is `None`). Without decay or cap a
/// warm register is the 5th, 50th and 95th percentiles of every frame rolled in (ruling R107).
pub fn roll_register(
    previous: Option<&RollingRegister>,
    voiced_st: &[f32],
    syllables: u32,
    params: &RollingParams,
) -> RollingRegister {
    let previous = previous.filter(|r| r.pool_usable());
    if syllables == 0 {
        return previous.cloned().unwrap_or_else(empty);
    }
    let mut pool = previous.map_or_else(|| vec![0.0; POOL_BINS], |r| r.pool.clone());
    let n_syllables = previous
        .map_or(0, |r| r.register.n_syllables)
        .saturating_add(syllables);
    let bins: Vec<usize> = voiced_st
        .iter()
        .filter(|st| st.is_finite())
        .map(|&st| bin_of(st))
        .collect();
    if !bins.is_empty() {
        let counted = counted_seconds(bins.len() as f64 * FRAME_S, params);
        let keep = decay(counted, params);
        for w in &mut pool {
            *w *= keep;
            if *w < NEGLIGIBLE_S {
                *w = 0.0;
            }
        }
        let each = counted / bins.len() as f64;
        for b in bins {
            pool[b] += each;
        }
    }
    RollingRegister {
        register: register_of(&pool, n_syllables),
        pool,
    }
}

/// The most seconds of speech one utterance counts as: `−half_life · log2(1 − max_share)`, the
/// weight whose share of a full pool (one half-life's worth, `half_life / ln 2`) is about
/// `max_share`. Unbounded without a cap.
pub fn utterance_cap_s(params: &RollingParams) -> Option<f64> {
    match (params.half_life_s, params.max_share) {
        (Some(h), Some(c)) => Some(-f64::from(h) * (1.0 - f64::from(c)).log2()),
        _ => None,
    }
}

/// How many seconds an utterance with `seconds` of voiced speech counts as.
fn counted_seconds(seconds: f64, params: &RollingParams) -> f64 {
    utterance_cap_s(params).map_or(seconds, |cap| seconds.min(cap))
}

/// What the pool keeps of its weight when `counted` seconds are added: `2^(−counted/half_life)`.
fn decay(counted: f64, params: &RollingParams) -> f64 {
    params
        .half_life_s
        .map_or(1.0, |h| (-counted / f64::from(h)).exp2())
}

/// The register a pool stands for after `n_syllables` syllables.
fn register_of(pool: &[f64], n_syllables: u32) -> Register {
    let total: f64 = pool.iter().sum();
    if total <= 0.0 {
        return fallback_register();
    }
    let warm = f64::from(n_syllables.min(WARM_SYLLABLES)) / f64::from(WARM_SYLLABLES);
    let margin = COLD_MARGIN_ST * (1.0 - warm);
    let at = |p: f64| weighted_percentile(pool, total, p);
    at_least_min_span(Register {
        floor_st: (at(0.05) - margin) as f32,
        median_st: at(0.5) as f32,
        ceil_st: (at(0.95) + margin) as f32,
        n_syllables,
    })
}

/// A rolling register that has learnt nothing: the fallback register over an empty pool.
fn empty() -> RollingRegister {
    RollingRegister {
        register: fallback_register(),
        pool: vec![0.0; POOL_BINS],
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::register::p5_p50_p95;

    /// Utterance `k`'s frames: a deterministic spread of pitches around 15 + (k mod 7) / 2 st.
    fn utterance(k: usize) -> Vec<f32> {
        (0..40 + 7 * (k % 5))
            .map(|i| 15.0 + (k % 7) as f32 * 0.5 + ((i * 37 + k * 11) % 53) as f32 * 0.2 - 5.0)
            .collect()
    }

    #[test]
    fn without_decay_a_warm_register_is_the_pooled_percentiles_of_every_frame() {
        // Ruling R107's pooling (and `cold_register`'s percentiles), to the pool's 0.1 st grid.
        let mut rolling = None;
        let mut all = Vec::new();
        for k in 0..20 {
            let frames = utterance(k);
            all.extend_from_slice(&frames);
            rolling = Some(roll_register(
                rolling.as_ref(),
                &frames,
                3,
                &RollingParams::POOLED,
            ));
        }
        let r = rolling.unwrap().register;
        assert_eq!(r.n_syllables, 60);
        let (p5, p50, p95) = p5_p50_p95(&all).unwrap();
        let grid = f64::from(tonekit_core::POOL_BIN_ST);
        for (got, want) in [(r.floor_st, p5), (r.median_st, p50), (r.ceil_st, p95)] {
            assert!(
                (f64::from(got) - want).abs() <= grid,
                "{got} vs pooled {want}"
            );
        }
    }

    #[test]
    fn while_cold_the_margin_shrinks_from_the_cold_starts_two_semitones() {
        let frames = utterance(0);
        let (p5, _, p95) = p5_p50_p95(&frames).unwrap();
        let grid = f64::from(tonekit_core::POOL_BIN_ST);
        // 0 syllables would learn nothing; 15 of 30 leaves half the margin; 30 leaves none.
        for (syllables, margin) in [(1, 2.0 * 29.0 / 30.0), (15, 1.0), (30, 0.0), (45, 0.0)] {
            let r = roll_register(None, &frames, syllables, &RollingParams::DEFAULT).register;
            assert!(
                (f64::from(r.floor_st) - (p5 - margin)).abs() <= grid,
                "{r:?}"
            );
            assert!(
                (f64::from(r.ceil_st) - (p95 + margin)).abs() <= grid,
                "{r:?}"
            );
        }
    }
}
