//! The syllable-duration prior of the closed-set DP (spec §7.2).

/// Seconds per frame.
pub(crate) const FRAME_S: f64 = 0.01;

/// The speaking rate `r` in seconds per syllable: the median interval between consecutive syllable
/// anchors (nucleus frames, or in the count stage the extra candidates' too, ruling R102) if there
/// are at least two, else `default_s`.
///
/// Anchors are taken in frame order. A median that is not a positive number (only possible with
/// hand-built nuclei sharing a frame) also falls back to `default_s`, so `r` is always usable as a
/// log-scale centre.
pub(crate) fn rate_s(frames: &[u32], default_s: f64) -> f64 {
    let mut frames = frames.to_vec();
    frames.sort_unstable();
    let mut gaps: Vec<u32> = frames.windows(2).map(|w| w[1] - w[0]).collect();
    if gaps.is_empty() {
        return default_s;
    }
    gaps.sort_unstable();
    let mid = gaps.len() / 2;
    let median = if gaps.len() % 2 == 1 {
        f64::from(gaps[mid])
    } else {
        0.5 * (f64::from(gaps[mid - 1]) + f64::from(gaps[mid]))
    };
    let r = median * FRAME_S;
    if r > 0.0 {
        r
    } else {
        default_s
    }
}

/// `dur(d) = −(ln(d/r))² / (2σ²)`: 0 at the speaking rate, symmetric in log-duration.
/// `d_s` and `r_s` are in seconds and positive.
pub(crate) fn log_prior(d_s: f64, r_s: f64, sigma: f64) -> f64 {
    let x = (d_s / r_s).ln();
    -(x * x) / (2.0 * sigma * sigma)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn nuclei(frames: &[u32]) -> Vec<u32> {
        frames.to_vec()
    }

    #[test]
    fn rate_is_the_median_inter_nucleus_interval() {
        // Intervals 30, 40, 20 → median 30 frames.
        assert!((rate_s(&nuclei(&[10, 40, 80, 100]), 0.22) - 0.30).abs() < 1e-12);
        // An even count of intervals averages the middle pair: 20, 30, 40, 50 → 35 frames.
        assert!((rate_s(&nuclei(&[0, 20, 50, 90, 140]), 0.22) - 0.35).abs() < 1e-12);
        // Order of the nuclei does not matter.
        assert!((rate_s(&nuclei(&[100, 10, 80, 40]), 0.22) - 0.30).abs() < 1e-12);
    }

    #[test]
    fn rate_falls_back_to_the_default() {
        assert_eq!(rate_s(&[], 0.22), 0.22);
        assert_eq!(rate_s(&nuclei(&[50]), 0.22), 0.22);
        assert_eq!(rate_s(&nuclei(&[50, 50]), 0.22), 0.22);
    }

    #[test]
    fn prior_peaks_at_the_rate_and_is_symmetric_in_log_duration() {
        assert_eq!(log_prior(0.25, 0.25, 0.4), 0.0);
        let short = log_prior(0.125, 0.25, 0.4);
        let long = log_prior(0.5, 0.25, 0.4);
        assert!((short - long).abs() < 1e-12);
        // −(ln 2)² / (2 · 0.4²) = −1.501.
        assert!((long + std::f64::consts::LN_2.powi(2) / 0.32).abs() < 1e-12);
    }
}
