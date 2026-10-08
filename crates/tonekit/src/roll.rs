//! `roll_register`: carry a speaker's register from utterance to utterance (ruling R111).

use tonekit_core::{
    Analysis, AssessError, Measured, RollingParams, RollingRegister, UtteranceAssessment,
};

/// The register to keep after grading an utterance, following the speaker as their register
/// drifts: `previous` (`None` for a speaker with nothing rolled in yet) with the utterance's
/// speech-only voiced frames (`analysis.voiced_st`, ruling R106) rolled in, older evidence
/// decaying under `params` (the pack's are `pack.calibration().rolling_register`).
///
/// Seed it with the register drill (roll each drill utterance in, starting from `None`) or with
/// the first graded utterances (a cold start), then pass `register` of the result to the next
/// `analyze`. Like `register_update` (which is unchanged), it learns only from an utterance with
/// a measured syllable (ruling R38): if every syllable of `assessment` is `NotMeasured`,
/// `previous` comes back as it is. Consumers persist the result only if `register.n_syllables >
/// 0`. A `previous` whose pool is not usable is started afresh. `assessment` must be the
/// assessment of `analysis`.
///
/// With [`RollingParams::POOLED`] (no decay, no cap) the warm register is the 5th, 50th and 95th
/// percentiles of every frame rolled in, as `tkh eval --register-from speaker` pools (ruling
/// R107). See `tonekit_shape::roll_register` for the arithmetic.
///
/// # Errors
///
/// [`AssessError::InvalidRequest`] for unusable `params` ([`RollingParams::problem`]).
pub fn roll_register(
    previous: Option<&RollingRegister>,
    analysis: &Analysis,
    assessment: &UtteranceAssessment,
    params: &RollingParams,
) -> Result<RollingRegister, AssessError> {
    if let Some(problem) = params.problem() {
        return Err(AssessError::InvalidRequest {
            message: format!("rolling register parameters: {problem}"),
        });
    }
    let measured = assessment
        .syllables
        .iter()
        .filter(|s| !matches!(s.measured, Measured::NotMeasured { .. }))
        .count();
    Ok(tonekit_shape::roll_register(
        previous,
        &analysis.voiced_st,
        u32::try_from(measured).unwrap_or(u32::MAX),
        params,
    ))
}
