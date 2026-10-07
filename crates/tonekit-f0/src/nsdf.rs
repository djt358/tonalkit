//! The normalised square-difference function: how well a stretch of signal repeats at a lag.

/// Samples the periodicity is measured over, centred on the frame (pYIN's autocorrelation window).
pub(crate) const WINDOW: usize = 512;

/// `2·Σ x[j]·x[j+lag] / Σ (x[j]² + x[j+lag]²)` over the window centred on `centre`, clamped to
/// `pcm`; 0 if the window holds no pair or no energy. Non-finite samples read as silence.
pub(crate) fn nsdf(pcm: &[f32], centre: usize, lag: usize) -> f64 {
    let start = centre.saturating_sub(WINDOW / 2);
    let end = (centre + WINDOW / 2).min(pcm.len());
    if end < start + lag + 1 {
        return 0.0;
    }
    let x = |k: usize| {
        let v = f64::from(pcm[k]);
        if v.is_finite() {
            v
        } else {
            0.0
        }
    };
    let (mut cross, mut power) = (0.0_f64, 0.0_f64);
    for j in start..end - lag {
        let (a, b) = (x(j), x(j + lag));
        cross += a * b;
        power += a * a + b * b;
    }
    if power > 0.0 {
        2.0 * cross / power
    } else {
        0.0
    }
}
