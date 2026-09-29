//! `assess`: grade an intended reading of an analysed utterance (spec §4.1, §6.3, §7.4).

use serde::{Deserialize, Serialize};
use tonekit_core::{
    AccentFit, AccentId, Analysis, AssessError, Candidate, DecodeResult, Evidence, GradingTarget,
    Measured, Register, RegisterSource, UtteranceAssessment,
};
use tonekit_decode::decode;
use tonekit_fuse::assemble;
use tonekit_pack::LanguagePack;
use tonekit_shape::merge_register;

/// What to grade. Owned and serialisable, so it crosses the FFI and JSON boundaries as it is.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct AssessRequest {
    /// The accent (and optional imprint style) the speaker is graded against.
    pub grading: GradingTarget,
    /// The reading the speaker was aiming for.
    pub intended: Candidate,
    /// Other readings it might be mistaken for; they compete with `intended` for `intended_rank`
    /// and `margin_llr`. Optional in JSON (default: none).
    #[serde(default)]
    pub distractors: Vec<Candidate>,
    /// Transcript or neural evidence about `intended`: empty, or one list per syllable. Optional
    /// in JSON (default: none).
    #[serde(default)]
    pub external: Vec<Vec<Evidence>>,
    /// Accents to report `accent_fit` for; nothing is reported for any other. Optional in JSON
    /// (default: none).
    #[serde(default)]
    pub compare_accents: Vec<AccentId>,
}

/// Grades `req.intended` against the utterance in `a`.
///
/// 1. `[intended] ∪ distractors` are decoded together under `req.grading`.
/// 2. Each accent in `req.compare_accents` re-decodes `[intended]` alone under that accent (no
///    imprint style) and reports its llr as an [`AccentFit`], in the order listed. There is
///    deliberately no way to ask which accent fits best across all of them (spec §11.5).
/// 3. `register_update` is the register to keep for next time, counting only the syllables of
///    `intended` that were measured (anything but `NotMeasured`; ruling R38). For a given register
///    it is that register merged with this utterance's voiced semitones and the measured count,
///    or unchanged (not even `n_syllables` moves) if nothing was measured. For a cold start it is
///    the analysis's own register (merging it back into itself would count the utterance twice),
///    with `n_syllables` 0 if nothing was measured. Consumers persist it only if
///    `n_syllables > 0`.
/// 4. `tonekit_fuse::assemble` fuses the acoustic judgements with `req.external` under the pack's
///    fusion weights. `margin_llr` is against the best rival or the null competitor's biased score
///    `null_llr + null_bias` (ruling R37), so a correct reading's margin is positive.
///
/// # Errors
///
/// Checked before any audio is scored:
/// - [`AssessError::DuplicateCandidate`] if two of `[intended] ∪ distractors` share an id;
/// - [`AssessError::EvidenceLengthMismatch`] unless `req.external` is empty or holds exactly one
///   list per syllable of `intended`.
///
/// From decoding: [`AssessError::UnknownTone`] for a tone outside the pack's inventory and
/// [`AssessError::Pack`] for anything the pack rejects, such as an unknown accent (in `grading` or
/// in `compare_accents`) or a candidate with no targets.
pub fn assess(
    a: &Analysis,
    pack: &LanguagePack,
    req: &AssessRequest,
) -> Result<UtteranceAssessment, AssessError> {
    let mut candidates = Vec::with_capacity(1 + req.distractors.len());
    candidates.push(req.intended.clone());
    candidates.extend(req.distractors.iter().cloned());
    check_ids_unique(&candidates)?;
    check_evidence_length(req)?;

    let decoded = decode(a, pack, &req.grading, &candidates)?;

    let accent_fit = req
        .compare_accents
        .iter()
        .map(|accent| fit_for_accent(a, pack, &req.intended, accent))
        .collect::<Result<Vec<_>, _>>()?;

    assemble(
        &decoded,
        &req.intended.id,
        &req.external,
        &pack.calibration().fusion,
        pack.calibration().decode.null_bias,
        accent_fit,
        register_update(a, measured_syllables(&decoded, &req.intended)),
    )
}

fn check_ids_unique(candidates: &[Candidate]) -> Result<(), AssessError> {
    for (n, candidate) in candidates.iter().enumerate() {
        if candidates[..n].iter().any(|c| c.id == candidate.id) {
            return Err(AssessError::DuplicateCandidate {
                id: candidate.id.clone(),
            });
        }
    }
    Ok(())
}

fn check_evidence_length(req: &AssessRequest) -> Result<(), AssessError> {
    let syllables = req.intended.targets.len();
    if req.external.is_empty() || req.external.len() == syllables {
        return Ok(());
    }
    Err(AssessError::EvidenceLengthMismatch {
        expected: count(syllables),
        got: count(req.external.len()),
    })
}

/// How well `intended` fits `a` when graded as `accent` speech, with no imprint style.
fn fit_for_accent(
    a: &Analysis,
    pack: &LanguagePack,
    intended: &Candidate,
    accent: &AccentId,
) -> Result<AccentFit, AssessError> {
    let grading = GradingTarget {
        accent: accent.clone(),
        style: None,
        style_weight: 0.0,
    };
    let decoded = decode(a, pack, &grading, std::slice::from_ref(intended))?;
    let llr = decoded
        .candidates
        .first()
        .map(|c| c.llr)
        .ok_or_else(|| AssessError::Pack {
            message: "accent comparison decoded no candidate".into(),
        })?;
    Ok(AccentFit {
        accent: accent.clone(),
        llr,
    })
}

/// How many syllables of `intended` were measured: those whose judgement is not `NotMeasured`
/// (the same test `SyllableAssessment::measured` carries into the assessment).
fn measured_syllables(decoded: &DecodeResult, intended: &Candidate) -> usize {
    decoded
        .candidates
        .iter()
        .find(|c| c.id == intended.id)
        .map_or(0, |c| {
            c.syllables
                .iter()
                .filter(|s| !matches!(s.judgement.measured, Measured::NotMeasured { .. }))
                .count()
        })
}

/// The register to keep after an utterance in which `measured` syllables were measured (R38).
fn register_update(a: &Analysis, measured: usize) -> Register {
    match (a.register_source, measured) {
        // Nothing to learn from: a given register stays as it is, and a cold start has no
        // syllables behind it, whatever its count says.
        (RegisterSource::Given, 0) => a.register.clone(),
        (RegisterSource::ColdStart, 0) => Register {
            n_syllables: 0,
            ..a.register.clone()
        },
        // Never merge a cold register into the utterance it was estimated from.
        (RegisterSource::ColdStart, _) => a.register.clone(),
        (RegisterSource::Given, u) => merge_register(&a.register, &a.voiced_st, count(u)),
    }
}

fn count(n: usize) -> u32 {
    u32::try_from(n).unwrap_or(u32::MAX)
}
