//! The judgement of an unpitched syllable (ruling R103): speech energy and a vowel's spectrum but
//! no pitch, scored on the calibration's evidence for such syllables instead of a contour. A place
//! whose table gives every tone the same value is no evidence (ruling R119).

use tonekit_core::{MeasureIssue, Measured, ToneJudgement, ToneTarget};

use crate::error::{invalid, PackError};
use crate::score::{clamp_log, logsumexp, LOG_CLAMP};
use crate::{LanguagePack, TargetContext};

/// How far apart a place's per-tone log-likelihoods must be for its table to be evidence (ruling
/// R119): when every tone is within this of every other, every tone's LLR is the same (0).
const FLAT_LLR: f64 = 1e-9;

/// Whether per-tone log-likelihoods tell the tones apart: some two differ by more than
/// [`FLAT_LLR`]. A pooled place (the same rate for every tone) does not.
fn tells_tones_apart(loglik: &[f32]) -> bool {
    let (lo, hi) = loglik
        .iter()
        .map(|&v| f64::from(v))
        .fold((f64::INFINITY, f64::NEG_INFINITY), |(lo, hi), v| {
            (lo.min(v), hi.max(v))
        });
    hi - lo > FLAT_LLR
}

impl LanguagePack {
    /// Judges `target` on a syllable in `ctx` that has speech energy and a vowel's spectrum but no
    /// pitch, or `None` when the calibration carries no unpitched evidence for the context's
    /// place: no `unpitched` section, or a place whose table gives every tone the same value
    /// (within 1e-9). Such a table (a pooled place) leaves every tone's LLR at 0, so it tells the
    /// tones apart no better than no table, and the syllable is no more measured than without one
    /// (ruling R119; the caller reports `NotMeasured { Unpitched }`).
    ///
    /// - `loglik[t]` is the calibration's `ln P(unpitched | t)` for the context's place (the end
    ///   of the phrase, or elsewhere), in inventory order; `-LOG_CLAMP` for a tone the table does
    ///   not name, so every value is finite (ruling R12).
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
            .map(|t| table.get(&t.0).copied().unwrap_or(-LOG_CLAMP as f32))
            .collect();
        if !tells_tones_apart(&loglik) {
            return Ok(None);
        }
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
            llr_target: clamp_log(llr),
            distance: None,
            component: None,
            heard,
            deltas: Vec::new(),
            measured: Measured::Partial { issues: all },
        }))
    }
}
