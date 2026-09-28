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
/// - `intended` must be one of `r.candidates`, otherwise [`AssessError::Pack`].
/// - `intended_rank` is the 1-based position in `r.candidates`, which is sorted by llr descending.
/// - `margin_llr` is the intended llr minus the larger of the best other candidate's llr and
///   `r.null_llr`; with no other candidates it is the intended llr minus `r.null_llr`.
/// - `overall` is the minimum `p_correct` over syllables that were measured (`Full` or `Partial`),
///   or `None` when no syllable was.
pub fn assemble(
    r: &DecodeResult,
    intended: &CandidateId,
    external: &[Vec<Evidence>],
    w: &FusionWeights,
    accent_fit: Vec<AccentFit>,
    register_update: Register,
) -> Result<UtteranceAssessment, AssessError> {
    let idx = r
        .candidates
        .iter()
        .position(|c| &c.id == intended)
        .ok_or_else(|| AssessError::Pack {
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
        .fold(r.null_llr, f32::max);

    let overall = syllables
        .iter()
        .filter(|s| !matches!(s.measured, Measured::NotMeasured { .. }))
        .map(|s| s.p_correct)
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
