//! `roll_register`: carry a speaker's register from utterance to utterance (ruling R111), and its
//! four-number form `roll_register_lite` (ruling R120).

use tonekit_core::{
    Analysis, AssessError, Measured, Register, RollingParams, RollingRegister, UtteranceAssessment,
};

use crate::analyze::usable;

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
/// R107). See `tonekit_shape::roll_register` for the arithmetic, and [`roll_register_lite`] for
/// a form that keeps four numbers instead of a pitch histogram.
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
    checked(params)?;
    Ok(tonekit_shape::roll_register(
        previous,
        &analysis.voiced_st,
        measured(assessment),
        params,
    ))
}

/// [`roll_register`] for an app that would rather not store a pitch histogram (ruling R120): the
/// register itself, four numbers, is all it keeps between utterances. Same half-life and
/// per-utterance cap (`params`), but each utterance moves floor, median and ceiling part of the
/// way to its own p5, p50 and p95 (an exponentially weighted average) instead of adding its frames
/// to a pool, so it is narrower than the full register and one far-off utterance moves all three
/// numbers in proportion to how far off it is (see `tonekit_shape::roll_register_lite`).
///
/// Pass the result to the next `analyze` and persist it only if `n_syllables > 0`, as with
/// `register_update`; with [`RollingParams::POOLED`] it is exactly the chain of `register_update`
/// merges from a cold start. A `previous` that cannot be graded against (what `analyze` reports
/// as `InvalidRegister`) is started afresh. `assessment` must be the assessment of `analysis`.
///
/// # Errors
///
/// [`AssessError::InvalidRequest`] for unusable `params` ([`RollingParams::problem`]).
pub fn roll_register_lite(
    previous: Option<&Register>,
    analysis: &Analysis,
    assessment: &UtteranceAssessment,
    params: &RollingParams,
) -> Result<Register, AssessError> {
    checked(params)?;
    Ok(tonekit_shape::roll_register_lite(
        previous.filter(|r| usable(r)),
        &analysis.voiced_st,
        measured(assessment),
        params,
    ))
}

/// `InvalidRequest` for parameters a rolling register cannot use.
fn checked(params: &RollingParams) -> Result<(), AssessError> {
    match params.problem() {
        Some(problem) => Err(AssessError::InvalidRequest {
            message: format!("rolling register parameters: {problem}"),
        }),
        None => Ok(()),
    }
}

/// How many of the assessment's syllables were measured (anything but `NotMeasured`, ruling R38).
fn measured(assessment: &UtteranceAssessment) -> u32 {
    let n = assessment
        .syllables
        .iter()
        .filter(|s| !matches!(s.measured, Measured::NotMeasured { .. }))
        .count();
    u32::try_from(n).unwrap_or(u32::MAX)
}
