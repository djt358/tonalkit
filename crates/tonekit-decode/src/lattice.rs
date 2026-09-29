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
//! `loglik_i(c) = logsumexp_p(ln γ_{i−1}(p) + e_i(p, c))` (`e_0(c)` at `i = 0`).

use tonekit_core::{
    Analysis, AssessError, GradingTarget, LatticeTbu, MeasureIssue, Measured, TbuSpan, ToneId,
    ToneLattice, ToneShape,
};
use tonekit_pack::{logsumexp, LanguagePack, TargetContext};

use crate::cache::{extract_span, merged_issues};
use crate::{clamp_log, count_u32, pack_err};

/// Schema string carried by every [`ToneLattice`].
pub(crate) const SCHEMA: &str = "tonekit.lattice.v1";

/// The TBU of each nucleus: from the nearest boundary strictly before the nucleus frame to the
/// nearest boundary strictly after it.
///
/// - With no boundary before (after) the nucleus, the TBU starts (ends) at `lo_edge` (`hi_edge`),
///   widened if need be so the nucleus frame stays inside.
/// - Neighbouring TBUs that would overlap — nuclei sharing both bounds, or a nucleus sitting on a
///   boundary — are cut at the frame midway between their nuclei (rounded up, so each nucleus
///   stays inside its own TBU).
///
/// `nuclei` and `bounds` are frame positions in any order; the TBUs follow the nuclei in time, one
/// per distinct nucleus frame, and never overlap.
pub(crate) fn tbu_spans(
    nuclei: &[u32],
    bounds: &[u32],
    lo_edge: u32,
    hi_edge: u32,
) -> Vec<TbuSpan> {
    let mut frames = nuclei.to_vec();
    frames.sort_unstable();
    frames.dedup();
    let mut spans: Vec<TbuSpan> = frames
        .iter()
        .map(|&f| TbuSpan {
            start_frame: bounds
                .iter()
                .copied()
                .filter(|&b| b < f)
                .max()
                .unwrap_or(lo_edge.min(f)),
            end_frame: bounds
                .iter()
                .copied()
                .filter(|&b| b > f)
                .min()
                .unwrap_or(hi_edge.max(f.saturating_add(1))),
        })
        .collect();
    for q in 1..spans.len() {
        if spans[q - 1].end_frame > spans[q].start_frame {
            let (left, right) = (frames[q - 1], frames[q]);
            let cut = left + (right - left).div_ceil(2);
            spans[q - 1].end_frame = cut;
            spans[q].start_frame = cut;
        }
    }
    spans
}

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

    // ln γ_i(c), normalised per TBU.
    let log_gamma: Vec<Vec<f64>> = (0..n)
        .map(|i| {
            let joint: Vec<f64> = (0..t).map(|c| alpha[i][c] + beta[i][c]).collect();
            let z = logsumexp(joint.iter().copied());
            if z.is_finite() {
                joint.iter().map(|v| v - z).collect()
            } else {
                // Unreachable with finite emissions and a positive prior; stay well-defined.
                vec![-(t as f64).ln(); t]
            }
        })
        .collect();
    // An unmeasured TBU's emission is 0 in every context, so its marginal is exactly 0 (the
    // logsumexp would give ln Σγ, 0 only up to rounding).
    let loglik = (0..n)
        .map(|i| match (&emissions[i], i) {
            (None, _) => vec![0.0; t],
            (Some(_), 0) => (0..t).map(|c| e(0, 0, c)).collect(),
            (Some(_), _) => (0..t)
                .map(|c| logsumexp((0..t).map(|p| log_gamma[i - 1][p] + e(i, p, c))))
                .collect(),
        })
        .collect();
    let posterior = log_gamma
        .iter()
        .map(|row| row.iter().map(|v| v.exp()).collect())
        .collect();
    Marginals { posterior, loglik }
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

/// The open lattice of `a` (grading already validated by the caller).
pub(crate) fn build(
    a: &Analysis,
    pack: &LanguagePack,
    g: &GradingTarget,
) -> Result<ToneLattice, AssessError> {
    let nuclei: Vec<u32> = a.nuclei.iter().map(|n| n.frame).collect();
    let (lo_edge, hi_edge) = match &a.speech {
        Some(r) => (r.start, r.end),
        None => (0, count_u32(a.f0.frames.len())),
    };
    let spans = tbu_spans(&nuclei, &a.boundaries, lo_edge, hi_edge);
    let n = spans.len();

    let mut units = Vec::with_capacity(n);
    let mut emissions = Vec::with_capacity(n);
    for (i, span) in spans.into_iter().enumerate() {
        match extract_span(a, span.start_frame, span.end_frame) {
            Ok(ex) => {
                let issues = merged_issues(&a.issues, &ex.issues);
                emissions.push(Some(emission(pack, g, &ex.shape, &issues, i, n)?));
                let measured = if issues.is_empty() {
                    Measured::Full
                } else {
                    Measured::Partial { issues }
                };
                units.push((span, measured, Some(ex.shape)));
            }
            Err(issue) => {
                emissions.push(None);
                units.push((span, Measured::NotMeasured { issue }, None));
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
    use crate::test_support::{cmn, hand_with, std_g, GAP, LEAD, SYLLABLE};
    use tonekit_core::{FrameRange, Nucleus};

    const EPS: f64 = 1e-9;

    fn span(start_frame: u32, end_frame: u32) -> TbuSpan {
        TbuSpan {
            start_frame,
            end_frame,
        }
    }

    fn ln(v: &[f64]) -> Vec<f64> {
        v.iter().map(|p| p.ln()).collect()
    }

    // --- TBU spans --------------------------------------------------------------------------

    #[test]
    fn tbus_take_the_nearest_boundaries_on_either_side() {
        let bounds = [20, 23, 33, 45, 48, 51, 76, 82, 108];
        assert_eq!(
            tbu_spans(&[31, 65, 102], &bounds, 20, 108),
            vec![span(23, 33), span(51, 76), span(82, 108)]
        );
        // A nucleus on a boundary is bounded by the ones strictly before and after it.
        assert_eq!(tbu_spans(&[48], &bounds, 20, 108), vec![span(45, 51)]);
    }

    #[test]
    fn tbus_fall_back_to_the_region_edges() {
        assert_eq!(tbu_spans(&[30], &[40, 60], 10, 90), vec![span(10, 40)]);
        assert_eq!(tbu_spans(&[70], &[40, 60], 10, 90), vec![span(60, 90)]);
        assert_eq!(tbu_spans(&[70], &[], 10, 90), vec![span(10, 90)]);
        // The fallback never leaves the nucleus outside its TBU.
        assert_eq!(tbu_spans(&[5], &[], 10, 90), vec![span(5, 90)]);
    }

    #[test]
    fn nuclei_sharing_both_bounds_split_midway() {
        // 30 and 50 both sit between boundaries 20 and 70: split at 40.
        assert_eq!(
            tbu_spans(&[50, 30], &[20, 70], 0, 100),
            vec![span(20, 40), span(40, 70)]
        );
        // Three in one gap: cuts at 35 and 55.
        assert_eq!(
            tbu_spans(&[30, 40, 70], &[20, 80], 0, 100),
            vec![span(20, 35), span(35, 55), span(55, 80)]
        );
        // Only the run that shares bounds is split.
        assert_eq!(
            tbu_spans(&[10, 30, 50], &[20, 70], 0, 100),
            vec![span(0, 20), span(20, 40), span(40, 70)]
        );
    }

    #[test]
    fn tbus_never_overlap_when_a_nucleus_sits_on_a_boundary() {
        // 40 is both a nucleus and a boundary: its TBU is (20, 60), and 50's is (40, 60).
        assert_eq!(
            tbu_spans(&[40, 50], &[20, 40, 60], 0, 100),
            vec![span(20, 45), span(45, 60)]
        );
        // A nucleus on a boundary right after its neighbour's nucleus.
        assert_eq!(
            tbu_spans(&[30, 40], &[20, 40, 60], 0, 100),
            vec![span(20, 35), span(35, 60)]
        );
    }

    #[test]
    fn every_nucleus_stays_inside_its_own_tbu() {
        // Odd and unit spacings round the cut up; a repeated nucleus is one TBU.
        assert_eq!(
            tbu_spans(&[30, 45], &[20, 70], 0, 100),
            vec![span(20, 38), span(38, 70)]
        );
        assert_eq!(
            tbu_spans(&[30, 31], &[20, 70], 0, 100),
            vec![span(20, 31), span(31, 70)]
        );
        assert_eq!(tbu_spans(&[30, 30], &[20, 70], 0, 100), vec![span(20, 70)]);
        for (nuclei, bounds) in [
            (vec![5, 12, 13, 40, 41, 90], vec![10, 13, 40, 60]),
            (vec![0, 1, 2], vec![]),
            (vec![50, 20, 80], vec![20, 50, 80]),
        ] {
            let spans = tbu_spans(&nuclei, &bounds, 0, 100);
            let mut sorted = nuclei.clone();
            sorted.sort_unstable();
            sorted.dedup();
            assert_eq!(spans.len(), sorted.len());
            for (s, &f) in spans.iter().zip(&sorted) {
                assert!(s.start_frame <= f && f < s.end_frame, "{f} in {s:?}");
            }
            for pair in spans.windows(2) {
                assert!(pair[0].end_frame <= pair[1].start_frame, "{spans:?}");
            }
        }
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
        let loglik = (0..n)
            .map(|i| {
                (0..t)
                    .map(|c| match i {
                        0 => e(0, 0, c),
                        _ => (0..t)
                            .map(|p| posterior[i - 1][p] * e(i, p, c).exp())
                            .sum::<f64>()
                            .ln(),
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
    fn loglik_marginalises_the_previous_tone_with_its_posterior() {
        let prior = ln(&[0.5, 0.5]);
        let second = vec![-4.0, 0.0, -1.0, -2.0];
        let m = forward_backward(&prior, &[Some(vec![0.0, -1.0]), Some(second.clone())]);
        let g0 = &m.posterior[0];
        for c in 0..2 {
            let want = (g0[0] * second[c].exp() + g0[1] * second[2 + c].exp()).ln();
            assert!((m.loglik[1][c] - want).abs() < 1e-9);
        }
        // The posterior of TBU 0 already sees TBU 1: B at TBU 0 explains TBU 1 better on the
        // whole (−1, −2 vs −4, 0 → logsumexp −0.69 vs 0.018), so it moves off e_0 alone.
        let alone = forward_backward(&prior, &[Some(vec![0.0, -1.0])]);
        assert!((g0[0] - alone.posterior[0][0]).abs() > 1e-3);
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
        let mut a = hand_with(&[
            (&[3.0, 5.0], true),
            (&[5.0, 1.0], false),
            (&[5.0, 5.0], true),
        ]);
        let starts: Vec<u32> = (0..3).map(|k| LEAD + k * (SYLLABLE + GAP)).collect();
        a.nuclei = starts
            .iter()
            .map(|&s| Nucleus {
                frame: s + SYLLABLE / 2,
                strength_db: 20.0,
            })
            .collect();
        a.boundaries = starts.iter().flat_map(|&s| [s, s + SYLLABLE]).collect();
        a.speech = Some(FrameRange {
            start: starts[0],
            end: starts[2] + SYLLABLE,
        });
        a
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
        let l = build(&two_unvoiced_one(), &pack, &g).unwrap();
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

        // TBU 2: phrase-final, its emission marginalised over TBU 1's posterior.
        let last = l.tbus[2].shape.as_ref().unwrap();
        for (c, tone) in tones.iter().enumerate() {
            let want = logsumexp(tones.iter().zip(&l.tbus[1].posterior).map(|(prev, &p)| {
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
    fn analysis_issues_mark_measured_tbus_partial() {
        let (pack, g) = (cmn(), std_g());
        let mut a = two_unvoiced_one();
        a.issues.push(MeasureIssue::LowSnr);
        let l = build(&a, &pack, &g).unwrap();
        let partial = Measured::Partial {
            issues: vec![MeasureIssue::LowSnr],
        };
        assert_eq!(l.tbus[0].measured, partial);
        assert_eq!(l.tbus[2].measured, partial);
        assert!(matches!(l.tbus[1].measured, Measured::NotMeasured { .. }));
        // The widened tolerances change the likelihoods.
        let clean = build(&two_unvoiced_one(), &pack, &g).unwrap();
        assert_ne!(l.tbus[0].loglik, clean.tbus[0].loglik);
    }

    #[test]
    fn no_nuclei_no_tbus() {
        let (pack, g) = (cmn(), std_g());
        let mut a = two_unvoiced_one();
        a.nuclei.clear();
        let l = build(&a, &pack, &g).unwrap();
        assert!(l.tbus.is_empty());
        assert_eq!(l.schema, SCHEMA);
    }
}
