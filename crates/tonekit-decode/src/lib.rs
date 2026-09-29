//! Closed-set decoding of any syllable count and the open tone lattice (spec §7.2–7.3).
//!
//! - [`decode`] scores caller candidates of *any* length against the whole utterance: a segmental
//!   DP over the analysis's boundary candidates places each candidate's targets on syllables,
//!   scoring each by its LLR against a background of all tones plus a log-duration prior, and
//!   charges speech it leaves unused (hesitations, restarts, extra words) as filler. Candidates
//!   compete in one softmax with a null "something else was said" competitor.
//! - [`lattice`] gives one tone-bearing unit per nucleus with per-tone likelihoods and posteriors
//!   from forward–backward over (previous tone, current tone), so context-dependent realisations
//!   (the neutral tone, the half third) are scored in context.
//!
//! Every f32 either returns is finite (ruling R12): log-values are clamped to `±1.0e6`.

#![forbid(unsafe_code)]

mod cache;
mod closed;
mod duration;
mod lattice;
mod null;

use tonekit_core::{
    Analysis, AssessError, Candidate, DecodeResult, GradingTarget, ToneId, ToneLattice,
};
use tonekit_pack::{LanguagePack, PackError, TargetContext};

use crate::closed::{contexts, Decoder};

/// Log-values are clamped into `[-LOG_CLAMP, LOG_CLAMP]` (ruling R12).
const LOG_CLAMP: f64 = 1.0e6;

/// Scores `candidates` against the utterance in `a`, graded against `g`.
///
/// Each candidate's `llr` is its best path: the sum of its syllables' target LLRs and duration
/// priors, less `filler_per_frame` for every speech frame no syllable covers. A candidate whose
/// targets cannot all be placed (no speech region, or too few boundaries) scores
/// `K × unvoiced_syllable_llr` with every syllable `NotMeasured { Unvoiced }` at an empty span
/// where the speech region starts. Posteriors are a softmax over the candidates' llrs and the
/// null competitor's `null_llr + null_bias`; candidates come back sorted by llr, highest first
/// (ties keep the caller's order).
///
/// Errors, all raised before any audio is scored:
/// - `Pack { "empty candidate set" }` for no candidates;
/// - `DuplicateCandidate` for a repeated id;
/// - `Pack { "candidate <id> has no targets" }` for a candidate with no targets;
/// - `UnknownTone` for a target or lexical-variant tone outside the pack's inventory;
/// - `Pack` for anything the pack rejects (unknown accent, bad variant weights, bad style).
pub fn decode(
    a: &Analysis,
    pack: &LanguagePack,
    g: &GradingTarget,
    candidates: &[Candidate],
) -> Result<DecodeResult, AssessError> {
    check_candidates(pack, candidates)?;
    check_grading(pack, g)?;
    for cand in candidates {
        for (target, ctx) in cand.targets.iter().zip(contexts(&cand.targets)) {
            pack.expect(g, target, &ctx).map_err(pack_err)?;
        }
    }

    let null_llr = null::null_llr(&lattice::build(a, pack, g)?);
    let mut decoder = Decoder::new(a, pack, g);
    let mut scores = Vec::with_capacity(candidates.len());
    for cand in candidates {
        scores.push(decoder.score(cand)?);
    }

    let d = &pack.calibration().decode;
    let null_score = f64::from(null_llr) + f64::from(d.null_bias);
    let llrs: Vec<f32> = scores.iter().map(|s| s.llr).collect();
    let (shares, null_posterior) = null::posteriors(&llrs, null_score);
    for (score, share) in scores.iter_mut().zip(shares) {
        score.posterior = share;
    }
    // `sort_by` is stable: equal llrs keep the caller's order.
    scores.sort_by(|x, y| y.llr.total_cmp(&x.llr));
    Ok(DecodeResult {
        candidates: scores,
        null_llr,
        null_posterior,
    })
}

/// The open tone lattice of `a` under `g`: one TBU per nucleus, each bounded by the nearest
/// boundary candidates on either side, with context-marginalised `loglik`, `posterior` (summing
/// to 1), `measured` and the shape.
///
/// Errors: `Pack` for anything the pack rejects about `g` (unknown accent, bad style), even when
/// the analysis has no nuclei.
pub fn lattice(
    a: &Analysis,
    pack: &LanguagePack,
    g: &GradingTarget,
) -> Result<ToneLattice, AssessError> {
    check_grading(pack, g)?;
    lattice::build(a, pack, g)
}

/// The caller-input checks of [`decode`] that need no grading, in candidate order.
fn check_candidates(pack: &LanguagePack, candidates: &[Candidate]) -> Result<(), AssessError> {
    if candidates.is_empty() {
        return Err(AssessError::Pack {
            message: "empty candidate set".into(),
        });
    }
    for (n, cand) in candidates.iter().enumerate() {
        if candidates[..n].iter().any(|c| c.id == cand.id) {
            return Err(AssessError::DuplicateCandidate {
                id: cand.id.clone(),
            });
        }
        if cand.targets.is_empty() {
            return Err(AssessError::Pack {
                message: format!("candidate {} has no targets", cand.id.0),
            });
        }
        for target in &cand.targets {
            let variants = target.lexical_variants.iter().map(|v| &v.tone);
            for tone in std::iter::once(&target.tone).chain(variants) {
                if tone_index(pack, tone).is_none() {
                    return Err(AssessError::UnknownTone { tone: tone.clone() });
                }
            }
        }
    }
    Ok(())
}

/// Resolves every inventory tone once, so a grading the pack rejects is an error even when there
/// is nothing to score.
fn check_grading(pack: &LanguagePack, g: &GradingTarget) -> Result<(), AssessError> {
    let first = TargetContext {
        index: 0,
        count: 1,
        prev: None,
        phrase_final: true,
    };
    for tone in pack.inventory() {
        pack.expect_tone(g, tone, &first).map_err(pack_err)?;
    }
    Ok(())
}

pub(crate) fn pack_err(e: PackError) -> AssessError {
    AssessError::Pack {
        message: e.to_string(),
    }
}

/// The inventory index of `tone`, if the pack has it.
pub(crate) fn tone_index(pack: &LanguagePack, tone: &ToneId) -> Option<usize> {
    pack.inventory().iter().position(|t| t == tone)
}

/// `v` as a finite f32 in `[-LOG_CLAMP, LOG_CLAMP]`; NaN reads as the lower bound (ruling R12).
pub(crate) fn clamp_log(v: f64) -> f32 {
    if v.is_nan() {
        -LOG_CLAMP as f32
    } else {
        v.clamp(-LOG_CLAMP, LOG_CLAMP) as f32
    }
}

/// A count or index as the u32 the core types carry (saturating; never reached in practice).
pub(crate) fn count_u32(n: usize) -> u32 {
    u32::try_from(n).unwrap_or(u32::MAX)
}

/// Fixtures shared by the unit tests: the shipped cmn pack and hand-built analyses.
#[cfg(test)]
pub(crate) mod test_support {
    use tonekit_core::{
        AccentId, Analysis, EnergyTrack, F0Frame, F0Track, GradingTarget, RegisterSource, ToneId,
        ToneTarget,
    };
    use tonekit_pack::{LanguagePack, TargetContext};
    use tonekit_testkit::{chao_to_hz, register_for};

    const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
    const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");

    /// Leading silent frames of [`hand`].
    pub(crate) const LEAD: u32 = 10;
    /// Frames per syllable of [`hand`].
    pub(crate) const SYLLABLE: u32 = 25;
    /// Silent frames after each syllable of [`hand`].
    pub(crate) const GAP: u32 = 6;

    pub(crate) fn cmn() -> LanguagePack {
        LanguagePack::from_toml(CMN_TOML, Some(CMN_CALIB)).unwrap()
    }

    pub(crate) fn std_g() -> GradingTarget {
        GradingTarget {
            accent: AccentId("cmn-standard".into()),
            style: None,
            style_weight: 0.0,
        }
    }

    pub(crate) fn target(tone: &str, label: Option<&str>) -> ToneTarget {
        ToneTarget {
            tone: ToneId(tone.into()),
            lexical_variants: Vec::new(),
            label: label.map(String::from),
        }
    }

    /// A context in a three-syllable phrase.
    pub(crate) fn ctx(index: u32, prev: Option<&str>, phrase_final: bool) -> TargetContext {
        TargetContext {
            index,
            count: 3,
            prev: prev.map(|p| ToneId(p.into())),
            phrase_final,
        }
    }

    /// [`hand_with`] with every syllable voiced at 0.9.
    pub(crate) fn hand(sylls: &[&[f32]]) -> Analysis {
        let voiced: Vec<(&[f32], f32)> = sylls.iter().map(|&k| (k, 0.9)).collect();
        hand_with(&voiced)
    }

    /// A hand-built analysis of exact f0: `LEAD` silent frames, then per `(knots, voiced_p)` a
    /// `SYLLABLE`-frame syllable following the Chao knots (linear between them) at that
    /// `voiced_p`, then `GAP` silent frames; a 100–200 Hz speaker with a warm register. Energy is
    /// −20 dB on syllables and −100 dB elsewhere. Nuclei, boundaries and the speech region are
    /// left empty for the test to set.
    pub(crate) fn hand_with(sylls: &[(&[f32], f32)]) -> Analysis {
        let silent = F0Frame {
            hz: None,
            voiced_p: 0.0,
        };
        let mut frames = vec![silent.clone(); LEAD as usize];
        let mut db = vec![-100.0; LEAD as usize];
        for &(knots, voiced_p) in sylls {
            let last = SYLLABLE - 1;
            for f in 0..SYLLABLE {
                let u = f as f32 / last as f32 * (knots.len() - 1) as f32;
                let k = (u.floor() as usize).min(knots.len().saturating_sub(2));
                let chao = if knots.len() == 1 {
                    knots[0]
                } else {
                    knots[k] + (u - k as f32) * (knots[k + 1] - knots[k])
                };
                frames.push(F0Frame {
                    hz: Some(chao_to_hz(chao, 100.0, 200.0)),
                    voiced_p,
                });
                db.push(-20.0);
            }
            frames.extend(std::iter::repeat_n(silent.clone(), GAP as usize));
            db.extend(std::iter::repeat_n(-100.0, GAP as usize));
        }
        Analysis {
            f0: F0Track {
                frames,
                provider: "hand".into(),
            },
            energy: EnergyTrack { db },
            nuclei: Vec::new(),
            boundaries: Vec::new(),
            speech: None,
            register: register_for(100.0, 200.0),
            register_source: RegisterSource::Given,
            voiced_st: Vec::new(),
            issues: Vec::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clamp_log_is_finite() {
        assert_eq!(clamp_log(f64::NAN), -1.0e6);
        assert_eq!(clamp_log(f64::NEG_INFINITY), -1.0e6);
        assert_eq!(clamp_log(f64::INFINITY), 1.0e6);
        assert_eq!(clamp_log(-2.5), -2.5);
    }

    #[test]
    fn count_u32_saturates() {
        assert_eq!(count_u32(7), 7);
        assert_eq!(count_u32(usize::MAX), u32::MAX);
    }
}
