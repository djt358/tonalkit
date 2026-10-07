//! The judgement of an unpitched syllable (ruling R103): speech energy and a vowel's spectrum but
//! no pitch, scored on the calibration's evidence for such syllables instead of a contour.

use tonekit_core::{MeasureIssue, Measured, ToneJudgement, ToneTarget};

use crate::error::{invalid, PackError};
use crate::score::logsumexp;
use crate::{LanguagePack, TargetContext};

impl LanguagePack {
    /// Judges `target` on a syllable in `ctx` that has speech energy and a vowel's spectrum but no
    /// pitch, or `None` when the calibration carries no unpitched evidence.
    ///
    /// - `loglik[t]` is the calibration's `ln P(unpitched | t)` for the context's place (the end
    ///   of the phrase, or elsewhere), in inventory order.
    /// - `llr_target` is the target's mixture (main tone and lexical variants by weight) against
    ///   the prior-weighted background of every tone, as for a shape (spec §7.1).
    /// - `heard` is the tone with the largest posterior if it reaches the heard threshold.
    /// - No distance, component or deltas: there is no contour. `measured` is
    ///   `Partial { [Unpitched] }` plus any of `issues` (the analysis's).
    ///
    /// Errors: `Invalid` for lexical-variant weights that are negative, not finite or outweigh 1,
    /// and `UnknownTone` for a tone outside the inventory.
    pub fn judge_unpitched(
        &self,
        target: &ToneTarget,
        ctx: &TargetContext,
        issues: &[MeasureIssue],
    ) -> Result<Option<ToneJudgement>, PackError> {
        let Some(evidence) = &self.calibration.unpitched else {
            return Ok(None);
        };
        let table = if ctx.phrase_final {
            &evidence.phrase_final
        } else {
            &evidence.other
        };
        let loglik: Vec<f32> = self
            .inventory
            .iter()
            .map(|t| table.get(&t.0).copied().unwrap_or(f32::NEG_INFINITY))
            .collect();
        let ll = |tone: &tonekit_core::ToneId| -> Result<f64, PackError> {
            let i = self
                .tone_index(tone)
                .ok_or_else(|| PackError::UnknownTone(tone.clone()))?;
            Ok(f64::from(loglik[i]))
        };

        let mut parts = Vec::with_capacity(1 + target.lexical_variants.len());
        let mut variant_sum = 0.0f32;
        for v in &target.lexical_variants {
            if !(v.weight.is_finite() && v.weight >= 0.0) {
                return invalid(format!(
                    "lexical variant {:?} has weight {}; weights must be >= 0",
                    v.tone.0, v.weight
                ));
            }
            variant_sum += v.weight;
            parts.push(f64::from(v.weight).ln() + ll(&v.tone)?);
        }
        let main = 1.0 - variant_sum;
        if main < -1e-6 {
            return invalid(format!(
                "lexical variant weights sum to {variant_sum}; they must leave the main tone a weight >= 0"
            ));
        }
        parts.push(f64::from(main.max(0.0)).ln() + ll(&target.tone)?);
        let scores: Vec<f64> = self
            .prior
            .iter()
            .zip(&loglik)
            .map(|(p, l)| f64::from(*p).ln() + f64::from(*l))
            .collect();
        let background = logsumexp(scores.iter().copied());
        let llr = logsumexp(parts) - background;

        let heard = scores
            .iter()
            .enumerate()
            .max_by(|a, b| a.1.total_cmp(b.1))
            .filter(|(_, s)| (*s - background).exp() >= f64::from(self.heard_threshold))
            .map(|(i, _)| self.inventory[i].clone());
        let mut all = vec![MeasureIssue::Unpitched];
        all.extend(
            issues
                .iter()
                .copied()
                .filter(|i| *i != MeasureIssue::Unpitched),
        );
        Ok(Some(ToneJudgement {
            expected: target.tone.clone(),
            loglik,
            llr_target: clamp(llr),
            distance: None,
            component: None,
            heard,
            deltas: Vec::new(),
            measured: Measured::Partial { issues: all },
        }))
    }
}

/// A log-value as a finite f32 (ruling R12).
fn clamp(v: f64) -> f32 {
    if v.is_nan() {
        -1.0e6
    } else {
        v.clamp(-1.0e6, 1.0e6) as f32
    }
}
