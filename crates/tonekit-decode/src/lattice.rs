//! The open tone lattice (spec §7.3): one tone-bearing unit per nucleus, with per-tone
//! likelihoods in context and posteriors from forward–backward over tone sequences.
//!
//! The state at TBU `i` is the pair (previous tone, current tone), so a realisation that depends
//! on the previous tone (the neutral tone, the half-third) is scored in its context. With the
//! pack's unigram prior as the transition, the chain collapses to a first-order chain over the
//! current tone whose emission at `i` reads the tone at `i − 1`:
//!
//! ```text
//! α_0(c) = ln prior(c) + e_0(c)
//! α_i(c) = ln prior(c) + logsumexp_p(α_{i−1}(p) + e_i(p, c))
//! β_i(p) = logsumexp_c(ln prior(c) + e_{i+1}(p, c) + β_{i+1}(c)),   β_{n−1} = 0
//! γ_i(c) ∝ exp(α_i(c) + β_i(c))
//! ```
//!
//! and the context-marginalised likelihood of TBU `i` is
//! `loglik_i(c) = logsumexp_p(ln α̂_{i−1}(p) + e_i(p, c))` (`e_0(c)` at `i = 0`), where
//! `α̂_{i−1} ∝ exp(α_{i−1})` is the previous tone's posterior given the TBUs up to it only. The full
//! posterior `γ_{i−1}` would already hold TBU `i`'s own evidence (through `β_{i−1}`) and count it
//! twice.

use tonekit_core::{
    Analysis, AssessError, GradingTarget, LatticeTbu, MeasureIssue, Measured, ToneId, ToneLattice,
    ToneShape,
};
use tonekit_pack::{logsumexp, LanguagePack, TargetContext};

use crate::cache::merged_issues;
use crate::evidence::Tbu;
use crate::{clamp_log, count_u32, pack_err};

/// Schema string carried by every [`ToneLattice`].
pub(crate) const SCHEMA: &str = "tonekit.lattice.v1";

/// Log-emissions of one TBU. `None` is unmeasured (0 for every state). Otherwise, for TBU 0 the
/// table holds `e_0(c)` (length `t`, no previous tone); for later TBUs `e_i(p, c)` at `p·t + c`.
pub(crate) type Emission = Option<Vec<f64>>;

/// Per-TBU posteriors and context-marginalised log-likelihoods.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct Marginals {
    pub posterior: Vec<Vec<f64>>,
    pub loglik: Vec<Vec<f64>>,
}

/// Forward–backward over `emissions` with transition score `log_prior[c]` (see the module docs).
/// Every posterior row sums to 1.
pub(crate) fn forward_backward(log_prior: &[f64], emissions: &[Emission]) -> Marginals {
    let t = log_prior.len();
    let n = emissions.len();
    let e = |i: usize, p: usize, c: usize| match &emissions[i] {
        None => 0.0,
        Some(table) if i == 0 => table[c],
        Some(table) => table[p * t + c],
    };

    let mut alpha = vec![vec![f64::NEG_INFINITY; t]; n];
    for i in 0..n {
        for c in 0..t {
            alpha[i][c] = if i == 0 {
                log_prior[c] + e(0, 0, c)
            } else {
                let prev = &alpha[i - 1];
                log_prior[c] + logsumexp((0..t).map(|p| prev[p] + e(i, p, c)))
            };
        }
    }
    let mut beta = vec![vec![0.0; t]; n];
    for i in (0..n.saturating_sub(1)).rev() {
        for p in 0..t {
            let next = &beta[i + 1];
            beta[i][p] = logsumexp((0..t).map(|c| log_prior[c] + e(i + 1, p, c) + next[c]));
        }
    }

    // ln γ_i(c) and ln α̂_i(c), normalised per TBU.
    let log_gamma: Vec<Vec<f64>> = (0..n)
        .map(|i| normalised(&(0..t).map(|c| alpha[i][c] + beta[i][c]).collect::<Vec<_>>()))
        .collect();
    let log_forward: Vec<Vec<f64>> = alpha.iter().map(|row| normalised(row)).collect();
    // An unmeasured TBU's emission is 0 in every context, so its marginal is exactly 0 (the
    // logsumexp would give ln Σα̂, 0 only up to rounding).
    let loglik = (0..n)
        .map(|i| match (&emissions[i], i) {
            (None, _) => vec![0.0; t],
            (Some(_), 0) => (0..t).map(|c| e(0, 0, c)).collect(),
            (Some(_), _) => (0..t)
                .map(|c| logsumexp((0..t).map(|p| log_forward[i - 1][p] + e(i, p, c))))
                .collect(),
        })
        .collect();
    let posterior = log_gamma
        .iter()
        .map(|row| row.iter().map(|v| v.exp()).collect())
        .collect();
    Marginals { posterior, loglik }
}

/// Log-values shifted to sum to 1 in probability; uniform if they cannot be (unreachable with
/// finite emissions and a positive prior, but kept well-defined).
fn normalised(log_values: &[f64]) -> Vec<f64> {
    let z = logsumexp(log_values.iter().copied());
    if z.is_finite() {
        log_values.iter().map(|v| v - z).collect()
    } else {
        vec![-(log_values.len() as f64).ln(); log_values.len()]
    }
}

/// The calibrated log-likelihood of every (previous, current) tone pair for TBU `i` of `n`.
fn emission(
    pack: &LanguagePack,
    g: &GradingTarget,
    shape: &ToneShape,
    issues: &[MeasureIssue],
    i: usize,
    n: usize,
) -> Result<Vec<f64>, AssessError> {
    let tones = pack.inventory();
    let prevs: Vec<Option<&ToneId>> = if i == 0 {
        vec![None]
    } else {
        tones.iter().map(Some).collect()
    };
    let mut table = Vec::with_capacity(prevs.len() * tones.len());
    for prev in prevs {
        let ctx = TargetContext {
            index: count_u32(i),
            count: count_u32(n),
            prev: prev.cloned(),
            phrase_final: i + 1 == n,
        };
        for cur in tones {
            let ll = pack
                .tone_loglik(g, shape, cur, &ctx, issues)
                .map_err(pack_err)?;
            table.push(f64::from(ll));
        }
    }
    Ok(table)
}

/// Whether every number a pack scores `x` on is finite; it reads any other shape as no evidence
/// (`LanguagePack::judge`, `NotMeasured { InvalidEvidence }`).
fn finite(x: &ToneShape) -> bool {
    x.onset.is_finite()
        && x.offset.is_finite()
        && x.contour.iter().all(|v| v.is_finite())
        && x.voiced_weights.iter().all(|v| v.is_finite())
}

/// The open lattice of `a` on its nuclei's evidence `tbus` ([`crate::evidence::tbus`]; grading
/// already validated by the caller). A TBU with no shape, or one holding a non-finite number (as
/// `judge` reads it: `NotMeasured { InvalidEvidence }`), carries no evidence.
pub(crate) fn build(
    a: &Analysis,
    pack: &LanguagePack,
    g: &GradingTarget,
    tbus: &[Tbu],
) -> Result<ToneLattice, AssessError> {
    let n = tbus.len();
    let mut units = Vec::with_capacity(n);
    let mut emissions = Vec::with_capacity(n);
    for (i, tbu) in tbus.iter().enumerate() {
        let segment = match &tbu.segment {
            Ok(ex) if finite(&ex.shape) => Ok(ex),
            // As `judge` reads it: numbers that mean nothing are no evidence, not a measurement.
            Ok(_) => Err(MeasureIssue::InvalidEvidence),
            Err(issue) => Err(*issue),
        };
        match segment {
            Ok(ex) => {
                let issues = merged_issues(&a.issues, &ex.issues);
                emissions.push(Some(emission(pack, g, &ex.shape, &issues, i, n)?));
                let measured = if issues.is_empty() {
                    Measured::Full
                } else {
                    Measured::Partial { issues }
                };
                units.push((tbu.span.clone(), measured, Some(ex.shape.clone())));
            }
            Err(issue) => {
                emissions.push(None);
                units.push((tbu.span.clone(), Measured::NotMeasured { issue }, None));
            }
        }
    }

    let log_prior: Vec<f64> = pack.prior().iter().map(|&p| f64::from(p).ln()).collect();
    let m = forward_backward(&log_prior, &emissions);
    let tbus = units
        .into_iter()
        .zip(m.posterior.iter().zip(&m.loglik))
        .map(|((span, measured, shape), (post, ll))| LatticeTbu {
            span,
            loglik: ll.iter().map(|&v| clamp_log(v)).collect(),
            posterior: post.iter().map(|&p| p as f32).collect(),
            measured,
            shape,
        })
        .collect();

    Ok(ToneLattice {
        schema: SCHEMA.to_string(),
        lect: pack.lect().clone(),
        accent: g.accent.clone(),
        inventory: pack.inventory().to_vec(),
        prior: pack.prior().to_vec(),
        tbus,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::evidence::tbus;
    use crate::test_support::{cmn, hand, hand_with, marked, std_g, target};

    const EPS: f64 = 1e-9;

    fn ln(v: &[f64]) -> Vec<f64> {
        v.iter().map(|p| p.ln()).collect()
    }

    // --- Forward–backward -------------------------------------------------------------------

    #[test]
    fn posteriors_sum_to_one() {
        let prior = ln(&[0.2, 0.3, 0.5]);
        let first = vec![-1.0, -3.0, -0.5];
        let pair = |k: f64| (0..9).map(|x| -(x as f64) * k).collect::<Vec<_>>();
        let m = forward_backward(
            &prior,
            &[Some(first), Some(pair(0.3)), None, Some(pair(1.1))],
        );
        assert_eq!(m.posterior.len(), 4);
        for row in &m.posterior {
            assert_eq!(row.len(), 3);
            assert!((row.iter().sum::<f64>() - 1.0).abs() < EPS);
            assert!(row.iter().all(|p| (0.0..=1.0).contains(p)));
        }
    }

    #[test]
    fn uninformative_tbus_give_the_prior() {
        let p = [0.2, 0.3, 0.5];
        let m = forward_backward(&ln(&p), &[None, None, None]);
        for (row, ll) in m.posterior.iter().zip(&m.loglik) {
            for (a, b) in row.iter().zip(p) {
                assert!((a - b).abs() < EPS);
            }
            assert!(ll.iter().all(|&v| v == 0.0));
        }
    }

    #[test]
    fn a_single_tbu_is_bayes_rule() {
        let p = [0.25, 0.75];
        let e = vec![0.0, -2.0];
        let m = forward_backward(&ln(&p), &[Some(e.clone())]);
        let z = 0.25 + 0.75 * (-2.0f64).exp();
        assert!((m.posterior[0][0] - 0.25 / z).abs() < EPS);
        assert_eq!(m.loglik[0], e);
    }

    #[test]
    fn context_dependent_emissions_follow_the_previous_tone() {
        // Two tones A=0, B=1, uniform prior. TBU 1's shape fits B only after A:
        // e_1(A, B) = 0, e_1(A, A) = e_1(B, A) = e_1(B, B) = −4.
        let prior = ln(&[0.5, 0.5]);
        let second = vec![-4.0, 0.0, -4.0, -4.0];
        // TBU 0 clearly A: B is the best reading of TBU 1.
        let after_a = forward_backward(&prior, &[Some(vec![0.0, -6.0]), Some(second.clone())]);
        assert!(after_a.posterior[1][1] > 0.9, "{after_a:?}");
        // TBU 0 clearly B: the same shape is no evidence for B (both readings score −4), so TBU 1
        // stays near even, off it only by the little mass left on A at TBU 0.
        let after_b = forward_backward(&prior, &[Some(vec![-12.0, 0.0]), Some(second)]);
        assert!((after_b.posterior[1][0] - 0.5).abs() < 0.01, "{after_b:?}");
    }

    /// Posteriors and context-marginalised log-likelihoods by enumerating every tone sequence:
    /// weight(c) = Π_i prior(c_i)·exp(e_i(c_{i−1}, c_i)).
    fn brute_force(prior: &[f64], emissions: &[Emission]) -> Marginals {
        let (t, n) = (prior.len(), emissions.len());
        let e = |i: usize, p: usize, c: usize| match &emissions[i] {
            None => 0.0,
            Some(table) if i == 0 => table[c],
            Some(table) => table[p * t + c],
        };
        let mut posterior = vec![vec![0.0; t]; n];
        let mut total = 0.0;
        for code in 0..t.pow(n as u32) {
            let seq: Vec<usize> = (0..n).map(|i| code / t.pow(i as u32) % t).collect();
            let w: f64 = (0..n)
                .map(|i| prior[seq[i]] * e(i, seq[i.saturating_sub(1)], seq[i]).exp())
                .product();
            for i in 0..n {
                posterior[i][seq[i]] += w;
            }
            total += w;
        }
        for row in &mut posterior {
            row.iter_mut().for_each(|v| *v /= total);
        }
        // The previous tone's distribution given the TBUs up to it only: enumerate the prefixes.
        let forward = |i: usize| -> Vec<f64> {
            let mut f = vec![0.0; t];
            for code in 0..t.pow(i as u32 + 1) {
                let seq: Vec<usize> = (0..=i).map(|j| code / t.pow(j as u32) % t).collect();
                f[seq[i]] += (0..=i)
                    .map(|j| prior[seq[j]] * e(j, seq[j.saturating_sub(1)], seq[j]).exp())
                    .product::<f64>();
            }
            let z: f64 = f.iter().sum();
            f.iter().map(|v| v / z).collect()
        };
        let loglik = (0..n)
            .map(|i| {
                (0..t)
                    .map(|c| match i {
                        0 => e(0, 0, c),
                        _ => {
                            let before = forward(i - 1);
                            (0..t)
                                .map(|p| before[p] * e(i, p, c).exp())
                                .sum::<f64>()
                                .ln()
                        }
                    })
                    .collect()
            })
            .collect();
        Marginals { posterior, loglik }
    }

    #[test]
    fn forward_backward_matches_enumeration() {
        let prior = [0.2, 0.3, 0.5];
        // Deterministic but irregular emissions; TBU 2 unmeasured.
        let table = |len: usize, seed: f64| -> Emission {
            Some(
                (0..len)
                    .map(|x| -((x as f64 * seed).sin().abs() * 5.0))
                    .collect(),
            )
        };
        let emissions = [
            table(3, 1.3),
            table(9, 0.7),
            None,
            table(9, 2.9),
            table(9, 1.1),
        ];
        let got = forward_backward(&ln(&prior), &emissions);
        let want = brute_force(&prior, &emissions);
        for (g, w) in got
            .posterior
            .iter()
            .flatten()
            .zip(want.posterior.iter().flatten())
        {
            assert!((g - w).abs() < 1e-12, "{got:?}\n{want:?}");
        }
        for (g, w) in got
            .loglik
            .iter()
            .flatten()
            .zip(want.loglik.iter().flatten())
        {
            assert!((g - w).abs() < 1e-9, "{got:?}\n{want:?}");
        }
    }

    #[test]
    fn loglik_marginalises_the_previous_tone_with_its_forward_posterior() {
        let prior = ln(&[0.5, 0.5]);
        let second = vec![-4.0, 0.0, -1.0, -2.0];
        let m = forward_backward(&prior, &[Some(vec![0.0, -1.0]), Some(second.clone())]);
        // TBU 0's tone given TBU 0 alone: prior × e_0, normalised.
        let z = 0.5 + 0.5 * (-1f64).exp();
        let f0 = [0.5 / z, 0.5 * (-1f64).exp() / z];
        for c in 0..2 {
            let want = (f0[0] * second[c].exp() + f0[1] * second[2 + c].exp()).ln();
            assert!((m.loglik[1][c] - want).abs() < 1e-12);
        }
        // Not its full posterior, which already sees TBU 1: B at TBU 0 explains TBU 1 better on
        // the whole (−1, −2 vs −4, 0 → logsumexp −0.69 vs 0.018), so γ_0 moves off e_0 alone, and
        // weighting by it would count TBU 1's evidence twice (final review M7).
        assert!((m.posterior[0][0] - f0[0]).abs() > 1e-3);
    }

    #[test]
    fn a_tbu_s_own_evidence_does_not_pick_its_context() {
        // A=0, B=1, uniform prior. TBU 0 says nothing; TBU 1's shape fits B only after A. γ_0
        // leans to A because of TBU 1, but TBU 1's likelihood of B weighs A and B as TBU 0 left
        // them, even.
        let prior = ln(&[0.5, 0.5]);
        let second = vec![-4.0, 0.0, -4.0, -4.0];
        let m = forward_backward(&prior, &[Some(vec![0.0, 0.0]), Some(second)]);
        assert!(m.posterior[0][0] > 0.6, "{m:?}");
        let want_b = (0.5f64 + 0.5 * (-4f64).exp()).ln();
        assert!((m.loglik[1][1] - want_b).abs() < 1e-12, "{m:?}");
    }

    #[test]
    fn an_unmeasured_tbu_carries_context_across() {
        // A=0, B=1. TBU 2 fits B only after B; TBU 1 is unmeasured, TBU 0 clearly B.
        // Nothing constrains TBU 1 except the prior and TBU 2's preference for a B before it.
        let prior = ln(&[0.5, 0.5]);
        let third = vec![-5.0, -5.0, -5.0, 0.0];
        let m = forward_backward(&prior, &[Some(vec![-8.0, 0.0]), None, Some(third)]);
        assert!(m.loglik[1].iter().all(|&v| v == 0.0));
        assert!(m.posterior[1][1] > 0.9, "{m:?}");
        assert!(m.posterior[2][1] > 0.9, "{m:?}");
    }

    #[test]
    fn empty_lattice() {
        let m = forward_backward(&ln(&[0.5, 0.5]), &[]);
        assert!(m.posterior.is_empty() && m.loglik.is_empty());
    }

    // --- The lattice of an analysis ---------------------------------------------------------

    /// Hand-built 2 / 4 / 1 syllables, the middle one whispered (speech with no pitch), with
    /// nuclei at their middles, boundaries at their edges and the speech region around them.
    fn two_unvoiced_one() -> Analysis {
        marked(hand_with(&[
            (&[3.0, 5.0], true),
            (&[5.0, 1.0], false),
            (&[5.0, 5.0], true),
        ]))
    }

    /// The lattice of `a` on its own evidence.
    fn built(a: &Analysis, pack: &LanguagePack, g: &GradingTarget) -> ToneLattice {
        build(a, pack, g, &tbus(a)).unwrap()
    }

    fn context(index: u32, prev: Option<&ToneId>, phrase_final: bool) -> TargetContext {
        TargetContext {
            index,
            count: 3,
            prev: prev.cloned(),
            phrase_final,
        }
    }

    #[test]
    fn lattice_emissions_are_scored_in_context() {
        let (pack, g) = (cmn(), std_g());
        let l = built(&two_unvoiced_one(), &pack, &g);
        let spans: Vec<(u32, u32)> = l
            .tbus
            .iter()
            .map(|t| (t.span.start_frame, t.span.end_frame))
            .collect();
        assert_eq!(spans, [(10, 35), (41, 66), (72, 97)]);
        let tones = pack.inventory();

        // TBU 0: e_0(None, c), the first of three and not final.
        let first = l.tbus[0].shape.as_ref().unwrap();
        assert_eq!(l.tbus[0].measured, Measured::Full);
        for (c, tone) in tones.iter().enumerate() {
            let ctx = context(0, None, false);
            let want = pack.tone_loglik(&g, first, tone, &ctx, &[]).unwrap();
            assert_eq!(l.tbus[0].loglik[c], want);
        }

        // TBU 1 has no shape: no evidence, and no shape reported.
        assert_eq!(
            l.tbus[1].measured,
            Measured::NotMeasured {
                issue: MeasureIssue::Unvoiced
            }
        );
        assert!(l.tbus[1].shape.is_none());
        assert!(l.tbus[1].loglik.iter().all(|&v| v == 0.0));

        // TBU 2: phrase-final, its emission marginalised over TBU 1's tone as the TBUs up to it
        // have it: with nothing heard at TBU 1, that is the prior.
        let last = l.tbus[2].shape.as_ref().unwrap();
        for (c, tone) in tones.iter().enumerate() {
            let want = logsumexp(tones.iter().zip(pack.prior()).map(|(prev, &p)| {
                let ctx = context(2, Some(prev), true);
                f64::from(p).ln() + f64::from(pack.tone_loglik(&g, last, tone, &ctx, &[]).unwrap())
            }));
            assert!((f64::from(l.tbus[2].loglik[c]) - want).abs() < 1e-5);
        }

        // The measured TBUs read as spoken; every posterior sums to 1.
        let best = |p: &[f32]| (0..p.len()).max_by(|&x, &y| p[x].total_cmp(&p[y])).unwrap();
        assert_eq!(tones[best(&l.tbus[0].posterior)].0, "2");
        assert_eq!(tones[best(&l.tbus[2].posterior)].0, "1");
        for tbu in &l.tbus {
            assert!((tbu.posterior.iter().sum::<f32>() - 1.0).abs() < 1e-5);
        }
    }

    #[test]
    fn a_neutral_tone_weighs_the_previous_tone_by_what_came_before_it() {
        // A half-third then a neutral tone at Chao 4. The pack expects a different "5" after each
        // of T1-T4, so TBU 1's likelihood mixes over TBU 0's tone, weighted by TBU 0's forward
        // posterior (prior × its own likelihood), not by its full posterior, which already leans
        // on TBU 1 (final review M7).
        let (pack, g) = (cmn(), std_g());
        let l = built(&marked(hand(&[&[2.0, 1.0], &[4.0]])), &pack, &g);
        let tones = pack.inventory();
        let first: Vec<f64> = pack
            .prior()
            .iter()
            .zip(&l.tbus[0].loglik)
            .map(|(&p, &ll)| f64::from(p).ln() + f64::from(ll))
            .collect();
        let z = logsumexp(first.iter().copied());
        let shape = l.tbus[1].shape.as_ref().unwrap();
        let mixed = |log_weight: &dyn Fn(usize) -> f64, c: usize| {
            logsumexp(tones.iter().enumerate().map(|(p, prev)| {
                let ctx = TargetContext {
                    index: 1,
                    count: 2,
                    prev: Some(prev.clone()),
                    phrase_final: true,
                };
                let ll = pack.tone_loglik(&g, shape, &tones[c], &ctx, &[]).unwrap();
                log_weight(p) + f64::from(ll)
            }))
        };
        let forward = |p: usize| first[p] - z;
        for c in 0..tones.len() {
            let want = mixed(&forward, c);
            assert!((f64::from(l.tbus[1].loglik[c]) - want).abs() < 1e-4, "{c}");
        }
        let neutral = tones.iter().position(|t| t.0 == "5").unwrap();
        let full = |p: usize| f64::from(l.tbus[0].posterior[p]).ln();
        assert!(
            (mixed(&full, neutral) - mixed(&forward, neutral)).abs() > 1e-3,
            "the two weightings agree here, so this test shows nothing"
        );
    }

    #[test]
    fn analysis_issues_mark_measured_tbus_partial() {
        let (pack, g) = (cmn(), std_g());
        let mut a = two_unvoiced_one();
        a.issues.push(MeasureIssue::LowSnr);
        let l = built(&a, &pack, &g);
        let partial = Measured::Partial {
            issues: vec![MeasureIssue::LowSnr],
        };
        assert_eq!(l.tbus[0].measured, partial);
        assert_eq!(l.tbus[2].measured, partial);
        assert!(matches!(l.tbus[1].measured, Measured::NotMeasured { .. }));
        // The widened tolerances change the likelihoods.
        let clean = built(&two_unvoiced_one(), &pack, &g);
        assert_ne!(l.tbus[0].loglik, clean.tbus[0].loglik);
    }

    #[test]
    fn a_non_finite_shape_is_not_measured_as_judge_has_it() {
        // Unreachable from `analyze`, which only feeds finite numbers, but the lattice reads a
        // TBU with a NaN in its shape as `judge` does: `NotMeasured { InvalidEvidence }`, no
        // evidence and no shape reported, not `Full` on numbers that mean nothing.
        let (pack, g) = (cmn(), std_g());
        let a = marked(hand(&[&[2.0, 1.0], &[5.0, 5.0], &[4.0]]));
        let clean = tbus(&a);
        let invalid = MeasureIssue::InvalidEvidence;
        let ctx = TargetContext {
            index: 1,
            count: 3,
            prev: None,
            phrase_final: false,
        };
        // The same lattice as for a TBU that had no shape for that reason.
        let mut shapeless = clean.clone();
        shapeless[1].segment = Err(invalid);
        let want = build(&a, &pack, &g, &shapeless).unwrap();
        assert_eq!(
            want.tbus[1].measured,
            Measured::NotMeasured { issue: invalid }
        );

        let poisons: [fn(&mut ToneShape); 4] = [
            |x| x.contour[4] = f32::NAN,
            |x| x.voiced_weights[0] = f32::INFINITY,
            |x| x.onset = f32::NAN,
            |x| x.offset = f32::NEG_INFINITY,
        ];
        for (n, poison) in poisons.into_iter().enumerate() {
            let mut spoiled = clean.clone();
            poison(&mut spoiled[1].segment.as_mut().unwrap().shape);
            let shape = &spoiled[1].segment.as_ref().unwrap().shape;
            let judged = pack
                .judge(&g, shape, &target("1", None), &ctx, &[])
                .unwrap();
            assert_eq!(judged.measured, want.tbus[1].measured, "{n}");

            let l = build(&a, &pack, &g, &spoiled).unwrap();
            assert_eq!(l, want, "{n}");
            assert!(l.tbus[1].shape.is_none());
            assert!(l.tbus[1].loglik.iter().all(|&v| v == 0.0));
            // Its neighbours are measured as before.
            assert_eq!(l.tbus[0].measured, Measured::Full);
            assert_eq!(l.tbus[2].measured, Measured::Full);
        }
    }

    #[test]
    fn no_nuclei_no_tbus() {
        let (pack, g) = (cmn(), std_g());
        let mut a = two_unvoiced_one();
        a.nuclei.clear();
        let l = built(&a, &pack, &g);
        assert!(l.tbus.is_empty());
        assert_eq!(l.schema, SCHEMA);
    }
}
