//! Per-decode memo tables (spec §7.2 "segment cache"): one shape per boundary pair, and the
//! target LLRs of each shape per context.
//!
//! Every candidate in a decode searches the same boundary pairs, so a shape is extracted at most
//! once per pair however many candidates visit it. `judge` resolves an expectation for every
//! inventory tone on each call (≈2 µs), so the DP does not call it per edge. For a target without
//! lexical variants it reads a row of per-tone LLRs instead, computed from `tone_loglik` exactly
//! as `judge` computes `llr_target` (see [`tone_llrs`]) once per (pair, context class).
//!
//! A *context class* is a set of contexts under which the pack resolves the same expectation for
//! every inventory tone. A tone's likelihood depends on its context only through that expectation
//! (spec §7.1: the mixture over the expectation's components), so every context in a class gives
//! the same row. Classes are found by resolving the expectations, never by assuming which context
//! fields the pack reads, and they let candidates of different lengths and positions share rows.
//! Targets with lexical variants go through `judge`, memoised per (pair, target, context).
//! `judge` itself is only called for the syllables of chosen paths.

use std::collections::BTreeMap;

use tonekit_core::{
    Analysis, AssessError, GradingTarget, MeasureIssue, Measured, SyllableFit, TbuSpan,
    ToneJudgement, ToneTarget,
};
use tonekit_pack::{logsumexp, Expectation, LanguagePack, TargetContext};
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
    /// A target with no lexical variants: its main tone (an inventory index) in a context class.
    Tone { class: usize, tone: usize },
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
    /// Every context seen, with its class.
    contexts: Vec<(TargetContext, usize)>,
    /// Per class: the expectation of every inventory tone, and the first context seen in it.
    classes: Vec<(Vec<Expectation>, TargetContext)>,
    mixed: Vec<(ToneTarget, TargetContext)>,
    /// `(from, to, class)` → [`tone_llrs`] of that segment.
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
            classes: Vec::new(),
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
    /// Interning resolves everything scoring the target will need, so a pack error surfaces here
    /// rather than midway through a decode: every inventory tone in `ctx` (the background), and a
    /// target with lexical variants as a whole.
    ///
    /// Errors: `UnknownTone` for a main tone outside the inventory; `Pack` for anything the pack
    /// rejects (unknown accent, a tone it cannot realise in `ctx`, bad variant weights or style).
    pub(crate) fn key(
        &mut self,
        target: &ToneTarget,
        ctx: &TargetContext,
    ) -> Result<TargetKey, AssessError> {
        let class = self.class(ctx)?;
        if target.lexical_variants.is_empty() {
            let tone =
                tone_index(self.pack, &target.tone).ok_or_else(|| AssessError::UnknownTone {
                    tone: target.tone.clone(),
                })?;
            return Ok(TargetKey::Tone { class, tone });
        }
        let item = (
            ToneTarget {
                label: None,
                ..target.clone()
            },
            ctx.clone(),
        );
        if let Some(id) = self.mixed.iter().position(|x| *x == item) {
            return Ok(TargetKey::Mixed { id });
        }
        self.pack.expect(self.g, target, ctx).map_err(pack_err)?;
        self.mixed.push(item);
        Ok(TargetKey::Mixed {
            id: self.mixed.len() - 1,
        })
    }

    /// The context class of `ctx`: the first class whose expectations `ctx` resolves to.
    fn class(&mut self, ctx: &TargetContext) -> Result<usize, AssessError> {
        if let Some((_, class)) = self.contexts.iter().find(|(c, _)| c == ctx) {
            return Ok(*class);
        }
        let expectations = self
            .pack
            .inventory()
            .iter()
            .map(|tone| self.pack.expect_tone(self.g, tone, ctx))
            .collect::<Result<Vec<_>, _>>()
            .map_err(pack_err)?;
        let class = match self.classes.iter().position(|(e, _)| *e == expectations) {
            Some(class) => class,
            None => {
                self.classes.push((expectations, ctx.clone()));
                self.classes.len() - 1
            }
        };
        self.contexts.push((ctx.clone(), class));
        Ok(class)
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
            TargetKey::Tone { class, tone } => {
                if let Some(row) = self.rows.get(&(from, to, class)) {
                    return Ok(row[tone]);
                }
                let row = tone_llrs(pack, g, ex, &self.classes[class].1, &a.issues)?;
                let v = row[tone];
                self.rows.insert((from, to, class), row);
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
        let mut key = |t: &ToneTarget, c: &TargetContext| s.key(t, c).unwrap();
        let class = |k: TargetKey| match k {
            TargetKey::Tone { class, .. } => class,
            TargetKey::Mixed { .. } => panic!("{k:?}"),
        };
        let k = key(&target("3", None), &ctx(0, None, false));
        assert_eq!(key(&target("3", Some("mǎi")), &ctx(0, None, false)), k);
        // Another tone in the same context shares the class (and so its LLR rows).
        let k4 = key(&target("4", None), &ctx(0, None, false));
        assert_ne!(k4, k);
        assert_eq!(class(k4), class(k));
        // So does any context the pack resolves identically: cmn reads prev and phrase_final.
        let elsewhere = TargetContext {
            index: 4,
            count: 7,
            ..ctx(0, None, false)
        };
        assert_eq!(key(&target("3", None), &elsewhere), k);
        // Contexts the pack resolves differently get their own class: the neutral tone after
        // "1", and the phrase-final third.
        let after_1 = class(key(&target("3", None), &ctx(1, Some("1"), false)));
        let after_2 = class(key(&target("3", None), &ctx(1, Some("2"), false)));
        let last = class(key(&target("3", None), &ctx(2, None, true)));
        let classes = [class(k), after_1, after_2, last];
        for (i, x) in classes.iter().enumerate() {
            assert!(!classes[i + 1..].contains(x), "{classes:?}");
        }

        let m = key(&varied("3", "2", 0.3), &ctx(0, None, false));
        assert!(matches!(m, TargetKey::Mixed { .. }));
        assert_eq!(key(&varied("3", "2", 0.3), &ctx(0, None, false)), m);
        assert_ne!(key(&varied("3", "2", 0.4), &ctx(0, None, false)), m);
        assert_ne!(key(&varied("3", "2", 0.3), &ctx(1, None, false)), m);
        assert_eq!(
            s.key(&target("9", None), &ctx(0, None, false)),
            Err(AssessError::UnknownTone {
                tone: ToneId("9".into())
            })
        );
        // Interning resolves what scoring will need, so pack errors surface here.
        let heavy = s.key(&varied("3", "2", 1.5), &ctx(0, None, false));
        assert!(matches!(heavy, Err(AssessError::Pack { .. })), "{heavy:?}");
        let mut bad = std_g();
        bad.accent.0 = "cmn-XX".into();
        let mut s = Scorer::new(&a, &pack, &bad);
        let r = s.key(&target("1", None), &ctx(0, None, false));
        assert!(matches!(r, Err(AssessError::Pack { ref message }) if message.contains("cmn-XX")));
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
        // Each context is followed by one of the same class at another position, which reads
        // its rows from the first.
        let moved = |c: TargetContext| TargetContext {
            index: c.index + 3,
            count: 9,
            ..c
        };
        let contexts = [
            ctx(0, None, false),
            moved(ctx(0, None, false)),
            ctx(1, Some("3"), false),
            moved(ctx(1, Some("3"), false)),
            ctx(2, Some("3"), true),
            moved(ctx(2, Some("3"), true)),
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
