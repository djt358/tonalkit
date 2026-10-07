//! Creaky tails as tone evidence (ruling R108): a pitched syllable whose pitch gives way to creak
//! (speech with a vowel's spectrum and no pitch right after its last pitched frame,
//! `MeasureIssue::CreakyTail`) is more likely a falling or low tone than a level high one. The
//! calibration's `ln P(creaky tail | tone)` at the syllable's place is added to every tone's
//! log-likelihood of the shape.
//!
//! Only a tail that is there counts: a syllable without one gets no term. Many voices never creak,
//! and a synthetic one never does, so the absence of creak is not held against a tone that often
//! ends in it.

use tonekit_core::{MeasureIssue, ToneId, ToneTarget};

use crate::score::logsumexp;
use crate::{LanguagePack, TargetContext};

impl LanguagePack {
    /// `ln P(creaky tail | tone)` at `ctx`'s place (the end of the phrase, or elsewhere) when
    /// `issues` has `CreakyTail` and the calibration carries creaky-tail evidence; 0 otherwise.
    /// A tone the table does not name (the pack's load checks that it names them all) scores 0.
    pub(crate) fn tail_loglik(
        &self,
        tone: &ToneId,
        ctx: &TargetContext,
        issues: &[MeasureIssue],
    ) -> f32 {
        if !issues.contains(&MeasureIssue::CreakyTail) {
            return 0.0;
        }
        let Some(evidence) = &self.calibration.creaky_tail else {
            return 0.0;
        };
        let table = if ctx.phrase_final {
            &evidence.phrase_final
        } else {
            &evidence.other
        };
        table.get(&tone.0).copied().unwrap_or(0.0)
    }

    /// [`Self::tail_loglik`] of a target: its main tone's, or for a target with lexical variants
    /// `ln Σ wᵢ·P(creaky tail | toneᵢ)` over the main tone (weight 1 − Σ variant weights, at
    /// least 0) and the variants, each weight as given (the shape's scoring rejects bad ones).
    pub(crate) fn target_tail_loglik(
        &self,
        target: &ToneTarget,
        ctx: &TargetContext,
        issues: &[MeasureIssue],
    ) -> f32 {
        if target.lexical_variants.is_empty() || !issues.contains(&MeasureIssue::CreakyTail) {
            return self.tail_loglik(&target.tone, ctx, issues);
        }
        let variant_sum: f32 = target.lexical_variants.iter().map(|v| v.weight).sum();
        let parts = target
            .lexical_variants
            .iter()
            .map(|v| (v.weight, &v.tone))
            .chain([((1.0 - variant_sum).max(0.0), &target.tone)])
            .map(|(w, tone)| f64::from(w).ln() + f64::from(self.tail_loglik(tone, ctx, issues)));
        logsumexp(parts) as f32
    }
}

/// `ll + tail` as a finite calibrated log-value; `ll` itself, bit for bit, when `tail` is 0.
pub(crate) fn with_tail(ll: f32, tail: f32) -> f32 {
    if tail == 0.0 {
        ll
    } else {
        crate::score::clamp_log(f64::from(ll) + f64::from(tail))
    }
}
