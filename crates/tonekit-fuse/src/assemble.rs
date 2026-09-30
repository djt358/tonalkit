//! Utterance assembly (spec §7.4).

use tonekit_core::{
    AccentFit, AssessError, CandidateId, DecodeResult, Evidence, FusionWeights, Measured, Register,
    UtteranceAssessment,
};

use crate::syllable::fuse_syllable;

/// Schema string carried by every [`UtteranceAssessment`].
const SCHEMA: &str = "tonekit.assessment.v1";

fn as_u32(n: usize) -> u32 {
    u32::try_from(n).unwrap_or(u32::MAX)
}

/// Assembles the final assessment of the `intended` candidate from a closed-set decode.
///
/// - `external` is either empty (no external evidence) or holds exactly one `Vec<Evidence>` per
///   syllable of the intended candidate; anything else is [`AssessError::EvidenceLengthMismatch`].
/// - `intended` must be one of `r.candidates`, otherwise [`AssessError::InvalidRequest`].
/// - `intended_rank` is the 1-based position in `r.candidates`, which is sorted by llr descending.
/// - `margin_llr` is the intended llr minus the larger of the best other candidate's llr and the
///   null competitor's score `r.null_llr + null_bias` (the same biased score the decode's posterior
///   softmax gives the null, ruling R37); with no other candidates it is the intended llr minus
///   that null score. Against the raw `null_llr` a reading could at most tie (the null is the
///   best free choice of tones), so a correct reading's margin would sit at or below 0.
/// - `overall` is the minimum `p_correct` over the syllables that count: those that were measured
///   (`Full` or `Partial`) and those that carry a confusion hit (`heard_as` is `Some`), even if
///   unmeasured, because a hit is a specific miss and the veto has already capped its `p_correct`.
///   It is `None` only when no syllable is measured and none has a hit ("tone not checked"). A
///   counted `p_correct` that is not a number counts as 0: a syllable that cannot be graded fails
///   the cast rather than dropping out of it.
pub fn assemble(
    r: &DecodeResult,
    intended: &CandidateId,
    external: &[Vec<Evidence>],
    w: &FusionWeights,
    null_bias: f32,
    accent_fit: Vec<AccentFit>,
    register_update: Register,
) -> Result<UtteranceAssessment, AssessError> {
    let idx = r
        .candidates
        .iter()
        .position(|c| &c.id == intended)
        .ok_or_else(|| AssessError::InvalidRequest {
            message: "intended candidate missing".into(),
        })?;
    let chosen = &r.candidates[idx];

    if !external.is_empty() && external.len() != chosen.syllables.len() {
        return Err(AssessError::EvidenceLengthMismatch {
            expected: as_u32(chosen.syllables.len()),
            got: as_u32(external.len()),
        });
    }

    let syllables: Vec<_> = chosen
        .syllables
        .iter()
        .enumerate()
        .map(|(k, fit)| fuse_syllable(fit, external.get(k).map_or(&[], Vec::as_slice), w))
        .collect();

    let best_rival = r
        .candidates
        .iter()
        .enumerate()
        .filter(|&(i, _)| i != idx)
        .map(|(_, c)| c.llr)
        .fold(r.null_llr + null_bias, f32::max);

    let overall = syllables
        .iter()
        .filter(|s| !matches!(s.measured, Measured::NotMeasured { .. }) || s.heard_as.is_some())
        .map(|s| {
            if s.p_correct.is_nan() {
                0.0
            } else {
                s.p_correct
            }
        })
        .reduce(f32::min);

    Ok(UtteranceAssessment {
        schema: SCHEMA.into(),
        intended: intended.clone(),
        intended_rank: as_u32(idx + 1),
        margin_llr: chosen.llr - best_rival,
        syllables,
        overall,
        accent_fit,
        register_update,
    })
}
