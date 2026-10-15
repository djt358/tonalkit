//! Pitch scales: semitones re 55 Hz, the Chao scale of a speaker, and a speaker's warm register.

use tonekit_core::Register;

/// Semitones are measured re this frequency.
const REF_HZ: f64 = 55.0;
/// `n_syllables` of [`register_for`]: well past the cold-start threshold.
const WARM_SYLLABLES: u32 = 100;

pub(crate) fn hz_to_st(hz: f64) -> f64 {
    12.0 * (hz / REF_HZ).log2()
}

pub(crate) fn st_to_hz(st: f64) -> f64 {
    REF_HZ * (st / 12.0).exp2()
}

/// Semitones re 55 Hz at Chao value `chao` for a speaker with Chao 1 at `floor_hz` and Chao 5 at
/// `ceil_hz`.
pub(crate) fn chao_to_st_f64(chao: f64, floor_hz: f64, ceil_hz: f64) -> f64 {
    let (floor_st, ceil_st) = (hz_to_st(floor_hz), hz_to_st(ceil_hz));
    floor_st + (chao - 1.0) / 4.0 * (ceil_st - floor_st)
}

pub(crate) fn chao_to_hz_f64(chao: f64, floor_hz: f64, ceil_hz: f64) -> f64 {
    st_to_hz(chao_to_st_f64(chao, floor_hz, ceil_hz))
}

/// The pitch at Chao value `chao` for a speaker whose Chao 1 is `floor_hz` and Chao 5 is `ceil_hz`.
///
/// Interpolates in semitones re 55 Hz, so it is the exact inverse of
/// `chao = 1 + 4·(st − floor_st)/(ceil_st − floor_st)`. Unclamped: `chao` may lie outside `1..=5`.
pub fn chao_to_hz(chao: f32, floor_hz: f32, ceil_hz: f32) -> f32 {
    chao_to_hz_f64(f64::from(chao), f64::from(floor_hz), f64::from(ceil_hz)) as f32
}

/// The register of a speaker with the given floor and ceiling, already warm (`n_syllables` = 100).
pub fn register_for(floor_hz: f32, ceil_hz: f32) -> Register {
    let floor_st = hz_to_st(f64::from(floor_hz)) as f32;
    let ceil_st = hz_to_st(f64::from(ceil_hz)) as f32;
    Register {
        floor_st,
        median_st: 0.5 * (floor_st + ceil_st),
        ceil_st,
        n_syllables: WARM_SYLLABLES,
    }
}

/// Chao value at `u` in `0..=1` along `knots` (evenly spaced, linear between them).
pub(crate) fn chao_at(knots: &[f32], u: f64) -> f64 {
    let n = knots.len();
    if n == 1 {
        return f64::from(knots[0]);
    }
    let x = u.clamp(0.0, 1.0) * (n - 1) as f64;
    let i = (x.floor() as usize).min(n - 2);
    let t = x - i as f64;
    f64::from(knots[i]) * (1.0 - t) + f64::from(knots[i + 1]) * t
}
