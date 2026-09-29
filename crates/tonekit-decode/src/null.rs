//! The null competitor ("something else was said") and the candidate softmax (spec §7.2).

use tonekit_core::{Measured, ToneLattice};
use tonekit_pack::logsumexp;

use crate::clamp_log;

/// `Σ_tbu [max_t loglik_t − logsumexp_t(ln prior_t + loglik_t)]` over the lattice's measured TBUs:
/// the evidence for the best free choice of tone at every nucleus, against the background. Each
/// term is ≥ 0 when the prior sums to 1; it is floored at 0 so f32 rounding in the prior cannot
/// make it negative.
pub(crate) fn null_llr(lattice: &ToneLattice) -> f32 {
    let log_prior: Vec<f64> = lattice.prior.iter().map(|&p| f64::from(p).ln()).collect();
    let total: f64 = lattice
        .tbus
        .iter()
        .filter(|tbu| !matches!(tbu.measured, Measured::NotMeasured { .. }))
        .map(|tbu| {
            let best = tbu
                .loglik
                .iter()
                .map(|&v| f64::from(v))
                .fold(f64::NEG_INFINITY, f64::max);
            let background = logsumexp(
                log_prior
                    .iter()
                    .zip(&tbu.loglik)
                    .map(|(lp, &ll)| lp + f64::from(ll)),
            );
            (best - background).max(0.0)
        })
        .sum();
    clamp_log(total)
}

/// The softmax over `llrs` and the null competitor's `null_score` (`null_llr + null_bias`): each
/// candidate's share in `llrs` order, then the null's share. The shares sum to 1.
pub(crate) fn posteriors(llrs: &[f32], null_score: f64) -> (Vec<f32>, f32) {
    let scores = llrs.iter().map(|&v| f64::from(v));
    let z = logsumexp(scores.clone().chain(std::iter::once(null_score)));
    let share = |v: f64| (v - z).exp() as f32;
    (scores.map(share).collect(), share(null_score))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tonekit_core::{AccentId, LatticeTbu, Lect, MeasureIssue, TbuSpan, ToneId};

    fn tbu(loglik: &[f32], measured: Measured) -> LatticeTbu {
        LatticeTbu {
            span: TbuSpan {
                start_frame: 0,
                end_frame: 10,
            },
            loglik: loglik.to_vec(),
            posterior: vec![0.5; loglik.len()],
            measured,
            shape: None,
        }
    }

    fn lattice(prior: &[f32], tbus: Vec<LatticeTbu>) -> ToneLattice {
        ToneLattice {
            schema: "tonekit.lattice.v1".into(),
            lect: Lect("cmn".into()),
            accent: AccentId("cmn-standard".into()),
            inventory: (1..=prior.len()).map(|i| ToneId(i.to_string())).collect(),
            prior: prior.to_vec(),
            tbus,
        }
    }

    #[test]
    fn null_llr_sums_the_best_free_choice_against_the_background() {
        let prior = [0.25, 0.75];
        let l = lattice(
            &prior,
            vec![
                tbu(&[0.0, -2.0], Measured::Full),
                tbu(
                    &[-1.0, -1.0],
                    Measured::Partial {
                        issues: vec![MeasureIssue::TooShort],
                    },
                ),
                // Unmeasured TBUs carry no evidence, whatever their numbers.
                tbu(
                    &[5.0, -5.0],
                    Measured::NotMeasured {
                        issue: MeasureIssue::Unvoiced,
                    },
                ),
            ],
        );
        let first = 0.0 - (0.25f64 + 0.75 * (-2.0f64).exp()).ln();
        // Equal likelihoods: the best free choice is no better than the background.
        let second = 0.0;
        approx::assert_abs_diff_eq!(f64::from(null_llr(&l)), first + second, epsilon = 1e-6);
    }

    #[test]
    fn null_llr_is_zero_without_measured_tbus_and_never_negative() {
        assert_eq!(null_llr(&lattice(&[0.5, 0.5], Vec::new())), 0.0);
        // A prior summing to more than 1 would make the term negative; it is floored at 0.
        let l = lattice(&[0.6, 0.6], vec![tbu(&[-1.0, -1.0], Measured::Full)]);
        assert_eq!(null_llr(&l), 0.0);
        // Clamped log-likelihoods stay finite.
        let l = lattice(&[0.5, 0.5], vec![tbu(&[0.0, -1.0e6], Measured::Full)]);
        assert!(null_llr(&l).is_finite());
    }

    #[test]
    fn posteriors_are_a_softmax_including_the_null() {
        let (shares, null) = posteriors(&[1.0, 0.0], -1.0);
        let z = 1f64.exp() + 1.0 + (-1f64).exp();
        approx::assert_abs_diff_eq!(f64::from(shares[0]), 1f64.exp() / z, epsilon = 1e-6);
        approx::assert_abs_diff_eq!(f64::from(shares[1]), 1.0 / z, epsilon = 1e-6);
        approx::assert_abs_diff_eq!(f64::from(null), (-1f64).exp() / z, epsilon = 1e-6);
        // Far outside exp's range, still finite and summing to 1.
        let (shares, null) = posteriors(&[-1.0e6, 1.0e6], 0.0);
        assert_eq!((shares[0], shares[1], null), (0.0, 1.0, 0.0));
        let (shares, null) = posteriors(&[], 2.0);
        assert!(shares.is_empty());
        assert_eq!(null, 1.0);
    }
}
