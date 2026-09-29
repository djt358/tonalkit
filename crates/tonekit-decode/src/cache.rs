//! Per-decode memo tables (spec §7.2 "segment cache"): one shape per boundary pair, and the
//! target LLRs of each shape per context.
//!
//! Every candidate in a decode searches the same boundary pairs, so a shape is extracted at most
//! once per pair however many candidates visit it. `judge` resolves an expectation for every
//! inventory tone on each call (≈2 µs), so the DP does not call it per edge. For a target without
//! lexical variants it reads a row of per-tone LLRs instead, computed once per (pair, context)
//! from `tone_loglik` exactly as `judge` computes `llr_target` (see [`tone_llrs`]), and shared by
//! every candidate that places any tone in that context there — tone-minimal candidates share
//! most of their contexts. Targets with lexical variants go through `judge`, memoised per
//! (pair, target, context). `judge` itself is only called for the syllables of chosen paths.

use std::collections::BTreeMap;

use tonekit_core::{
    Analysis, AssessError, GradingTarget, MeasureIssue, Measured, SyllableFit, TbuSpan,
    ToneJudgement, ToneTarget,
};
use tonekit_pack::{logsumexp, LanguagePack, TargetContext};
use tonekit_shape::{extract, Extracted};

use crate::{clamp_log, pack_err, tone_index};

/// A segment's shape, or why there is none.
pub(crate) type Segment = Result<Extracted, MeasureIssue>;

/// The analysis-level issues followed by those of the extraction, without repeats.
pub(crate) fn merged_issues(
    analysis: &[MeasureIssue],
    extraction: &[MeasureIssue],
) -> Vec<MeasureIssue> {
    let mut issues = analysis.to_vec();
    for issue in extraction {
        if !issues.contains(issue) {
            issues.push(*issue);
        }
    }
    issues
}

/// The shape of frames `[from, to)` of `a`, normalised by its register.
pub(crate) fn extract_span(a: &Analysis, from: u32, to: u32) -> Segment {
    let span = TbuSpan {
        start_frame: from,
        end_frame: to,
    };
    extract(&a.f0, &span, &a.register)
}

/// The judgement of a syllable with no measurable shape: the target is expected, nothing was
/// heard, and the LLR is `llr` (`unvoiced_syllable_llr`).
pub(crate) fn unmeasured(target: &ToneTarget, issue: MeasureIssue, llr: f32) -> ToneJudgement {
    ToneJudgement {
        expected: target.tone.clone(),
        loglik: Vec::new(),
        llr_target: llr,
        distance: None,
        component: None,
        heard: None,
        deltas: Vec::new(),
        measured: Measured::NotMeasured { issue },
    }
}

/// Every inventory tone's LLR on `ex` in `ctx`, in inventory order: its calibrated
/// log-likelihood less the prior-weighted background of all tones.
///
/// This is `judge(..).llr_target` for a target without lexical variants, bit for bit: `judge`
/// scores such a target with its main tone's expectation, uses the same calibrated per-tone
/// log-likelihoods `tone_loglik` returns, and sums the background with the same accumulator in
/// the same order (`tonekit_pack::logsumexp`).
fn tone_llrs(
    pack: &LanguagePack,
    g: &GradingTarget,
    ex: &Extracted,
    ctx: &TargetContext,
    analysis_issues: &[MeasureIssue],
) -> Result<Vec<f32>, AssessError> {
    let issues = merged_issues(analysis_issues, &ex.issues);
    let loglik = pack
        .inventory()
        .iter()
        .map(|tone| pack.tone_loglik(g, &ex.shape, tone, ctx, &issues))
        .collect::<Result<Vec<f32>, _>>()
        .map_err(pack_err)?;
    let background = logsumexp(
        pack.prior()
            .iter()
            .zip(&loglik)
            .map(|(p, ll)| f64::from(*p).ln() + f64::from(*ll)),
    );
    Ok(loglik
        .iter()
        .map(|&ll| clamp_log(f64::from(ll) - background))
        .collect())
}

/// How the DP names a (target, context) pair; interned once per candidate by [`Scorer::key`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum TargetKey {
    /// A target with no lexical variants: its main tone (an inventory index) in an interned
    /// context.
    Tone { ctx: usize, tone: usize },
    /// A target with lexical variants, in its context: scored by `judge`.
    Mixed { id: usize },
}

/// Scores targets on the segments between boundary candidates, memoising shapes and LLRs.
pub(crate) struct Scorer<'a> {
    a: &'a Analysis,
    pack: &'a LanguagePack,
    g: &'a GradingTarget,
    unvoiced_llr: f32,
    segments: BTreeMap<(u32, u32), Segment>,
    contexts: Vec<TargetContext>,
    mixed: Vec<(ToneTarget, TargetContext)>,
    /// `(from, to, context)` → [`tone_llrs`] of that segment.
    rows: BTreeMap<(u32, u32, usize), Vec<f32>>,
    /// `(from, to, mixed id)` → `judge(..).llr_target`.
    mixed_llrs: BTreeMap<(u32, u32, usize), f32>,
}

impl<'a> Scorer<'a> {
    pub(crate) fn new(a: &'a Analysis, pack: &'a LanguagePack, g: &'a GradingTarget) -> Self {
        Scorer {
            a,
            pack,
            g,
            unvoiced_llr: pack.calibration().decode.unvoiced_syllable_llr,
            segments: BTreeMap::new(),
            contexts: Vec::new(),
            mixed: Vec::new(),
            rows: BTreeMap::new(),
            mixed_llrs: BTreeMap::new(),
        }
    }

    /// The LLR of an unmeasurable segment (`unvoiced_syllable_llr`).
    pub(crate) fn unvoiced_llr(&self) -> f32 {
        self.unvoiced_llr
    }

    /// The key of `target` in `ctx`, interning it on first sight. A target's `label` does not
    /// affect scoring, so targets that differ only in label share a key.
    ///
    /// Errors: `UnknownTone` for a main tone outside the inventory.
    pub(crate) fn key(
        &mut self,
        target: &ToneTarget,
        ctx: &TargetContext,
    ) -> Result<TargetKey, AssessError> {
        if target.lexical_variants.is_empty() {
            let tone =
                tone_index(self.pack, &target.tone).ok_or_else(|| AssessError::UnknownTone {
                    tone: target.tone.clone(),
                })?;
            let ctx = intern(&mut self.contexts, ctx, |a, b| a == b);
            return Ok(TargetKey::Tone { ctx, tone });
        }
        let unlabelled = ToneTarget {
            label: None,
            ..target.clone()
        };
        let id = intern(&mut self.mixed, &(unlabelled, ctx.clone()), |a, b| a == b);
        Ok(TargetKey::Mixed { id })
    }

    /// `judge(..).llr_target` of the target behind `key` on frames `[from, to)`, or
    /// `unvoiced_syllable_llr` if the segment has no shape.
    pub(crate) fn llr(&mut self, from: u32, to: u32, key: TargetKey) -> Result<f32, AssessError> {
        let (a, pack, g) = (self.a, self.pack, self.g);
        let segment = self
            .segments
            .entry((from, to))
            .or_insert_with(|| extract_span(a, from, to));
        let Ok(ex) = segment else {
            return Ok(self.unvoiced_llr);
        };
        match key {
            TargetKey::Tone { ctx, tone } => {
                if let Some(row) = self.rows.get(&(from, to, ctx)) {
                    return Ok(row[tone]);
                }
                let row = tone_llrs(pack, g, ex, &self.contexts[ctx], &a.issues)?;
                let v = row[tone];
                self.rows.insert((from, to, ctx), row);
                Ok(v)
            }
            TargetKey::Mixed { id } => {
                if let Some(&v) = self.mixed_llrs.get(&(from, to, id)) {
                    return Ok(v);
                }
                let (target, ctx) = &self.mixed[id];
                let issues = merged_issues(&a.issues, &ex.issues);
                let v = pack
                    .judge(g, &ex.shape, target, ctx, &issues)
                    .map_err(pack_err)?
                    .llr_target;
                self.mixed_llrs.insert((from, to, id), v);
                Ok(v)
            }
        }
    }

    /// The full judgement of `target` in `ctx` on frames `[from, to)`: `judge` on its shape, or
    /// [`unmeasured`] if it has none.
    pub(crate) fn fit(
        &mut self,
        from: u32,
        to: u32,
        target: &ToneTarget,
        ctx: &TargetContext,
    ) -> Result<SyllableFit, AssessError> {
        let a = self.a;
        let segment = self
            .segments
            .entry((from, to))
            .or_insert_with(|| extract_span(a, from, to));
        let judgement = match segment {
            Ok(ex) => {
                let issues = merged_issues(&a.issues, &ex.issues);
                self.pack
                    .judge(self.g, &ex.shape, target, ctx, &issues)
                    .map_err(pack_err)?
            }
            Err(issue) => unmeasured(target, *issue, self.unvoiced_llr),
        };
        Ok(SyllableFit {
            span: TbuSpan {
                start_frame: from,
                end_frame: to,
            },
            judgement,
        })
    }
}

/// The index of `item` in `table` under `same`, appending a copy if it is new.
fn intern<T: Clone>(table: &mut Vec<T>, item: &T, same: impl Fn(&T, &T) -> bool) -> usize {
    if let Some(i) = table.iter().position(|x| same(x, item)) {
        return i;
    }
    table.push(item.clone());
    table.len() - 1
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::{cmn, ctx, hand, std_g, target};
    use tonekit_core::{ToneId, WeightedTone};

    fn varied(tone: &str, variant: &str, weight: f32) -> ToneTarget {
        let mut t = target(tone, None);
        t.lexical_variants.push(WeightedTone {
            tone: ToneId(variant.into()),
            weight,
        });
        t
    }

    #[test]
    fn merged_issues_keep_order_without_repeats() {
        use MeasureIssue::*;
        assert_eq!(
            merged_issues(&[LowSnr], &[TooShort]),
            vec![LowSnr, TooShort]
        );
        assert_eq!(merged_issues(&[TooShort], &[TooShort]), vec![TooShort]);
        assert!(merged_issues(&[], &[]).is_empty());
    }

    #[test]
    fn keys_ignore_labels_but_not_tones_variants_or_context() {
        let (pack, g) = (cmn(), std_g());
        let a = hand(&[]);
        let mut s = Scorer::new(&a, &pack, &g);
        let k = s.key(&target("3", None), &ctx(0, None, false)).unwrap();
        assert_eq!(
            s.key(&target("3", Some("mǎi")), &ctx(0, None, false)),
            Ok(k)
        );
        // Another tone in the same context shares the context (and so its LLR row).
        let TargetKey::Tone { ctx: c3, .. } = k else {
            panic!("{k:?}")
        };
        let k4 = s.key(&target("4", None), &ctx(0, None, false)).unwrap();
        assert!(matches!(k4, TargetKey::Tone { ctx, .. } if ctx == c3));
        assert_ne!(k4, k);
        assert_ne!(s.key(&target("3", None), &ctx(1, None, false)), Ok(k));
        assert_ne!(s.key(&target("3", None), &ctx(0, Some("1"), false)), Ok(k));
        let m = s.key(&varied("3", "2", 0.3), &ctx(0, None, false)).unwrap();
        assert!(matches!(m, TargetKey::Mixed { .. }));
        assert_eq!(s.key(&varied("3", "2", 0.3), &ctx(0, None, false)), Ok(m));
        assert_ne!(s.key(&varied("3", "2", 0.4), &ctx(0, None, false)), Ok(m));
        assert_eq!(
            s.key(&target("9", None), &ctx(0, None, false)),
            Err(AssessError::UnknownTone {
                tone: ToneId("9".into())
            })
        );
    }

    #[test]
    fn cached_llrs_equal_judge_bit_for_bit() {
        let (pack, g) = (cmn(), std_g());
        let a = hand(&[&[2.0, 1.0], &[5.0, 5.0], &[4.0], &[2.0, 1.0, 4.0]]);
        let spans = [(10, 35), (41, 66), (72, 97), (103, 128), (10, 66), (30, 50)];
        let targets = [
            target("1", None),
            target("2", None),
            target("3", None),
            target("4", None),
            target("5", None),
            varied("3", "2", 0.4),
            varied("5", "1", 0.2),
        ];
        let contexts = [
            ctx(0, None, false),
            ctx(1, Some("3"), false),
            ctx(2, Some("3"), true),
            ctx(2, Some("1"), true),
        ];
        let mut s = Scorer::new(&a, &pack, &g);
        for &(from, to) in &spans {
            let ex = extract_span(&a, from, to).unwrap();
            for c in &contexts {
                for t in &targets {
                    let key = s.key(t, c).unwrap();
                    let want = pack
                        .judge(&g, &ex.shape, t, c, &ex.issues)
                        .unwrap()
                        .llr_target;
                    // Twice: once computed, once from the cache.
                    assert_eq!(s.llr(from, to, key).unwrap().to_bits(), want.to_bits());
                    assert_eq!(s.llr(from, to, key).unwrap().to_bits(), want.to_bits());
                    let fit = s.fit(from, to, t, c).unwrap();
                    assert_eq!(fit.judgement.llr_target.to_bits(), want.to_bits());
                    assert_eq!((fit.span.start_frame, fit.span.end_frame), (from, to));
                }
            }
        }
    }

    #[test]
    fn analysis_issues_reach_the_scores() {
        // A cold-start register widens every tolerance: the LLRs change, and judge sees it too.
        let (pack, g) = (cmn(), std_g());
        let (t, c) = (target("4", None), ctx(0, None, true));
        let mut a = hand(&[&[5.0, 1.0]]);
        let warm = {
            let mut s = Scorer::new(&a, &pack, &g);
            let k = s.key(&t, &c).unwrap();
            s.llr(10, 35, k).unwrap()
        };
        a.issues.push(MeasureIssue::ColdStartRegister);
        let mut s = Scorer::new(&a, &pack, &g);
        let k = s.key(&t, &c).unwrap();
        let cold = s.llr(10, 35, k).unwrap();
        assert_ne!(cold, warm);
        let fit = s.fit(10, 35, &t, &c).unwrap();
        assert_eq!(fit.judgement.llr_target, cold);
        assert_eq!(
            fit.judgement.measured,
            Measured::Partial {
                issues: vec![MeasureIssue::ColdStartRegister]
            }
        );
    }

    #[test]
    fn unvoiced_segments_score_the_unvoiced_llr_and_are_not_measured() {
        let (pack, g) = (cmn(), std_g());
        let a = hand(&[&[5.0, 5.0]]);
        let mut s = Scorer::new(&a, &pack, &g);
        let t = target("1", None);
        let c = ctx(0, None, true);
        for key in [
            s.key(&t, &c).unwrap(),
            s.key(&varied("1", "2", 0.5), &c).unwrap(),
        ] {
            // Frames 0..10 are silent.
            assert_eq!(s.llr(0, 10, key), Ok(-3.0));
        }
        let fit = s.fit(0, 10, &t, &c).unwrap();
        assert_eq!(fit.judgement, unmeasured(&t, MeasureIssue::Unvoiced, -3.0));
        assert_eq!(fit.judgement.expected, t.tone);
        assert!(fit.judgement.loglik.is_empty() && fit.judgement.heard.is_none());
    }
}
