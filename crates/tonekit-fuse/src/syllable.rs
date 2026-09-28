//! Per-syllable fusion (spec §7.4).

use tonekit_core::{
    ConfusionHit, Evidence, EvidenceKind, FusionWeights, Measured, SyllableAssessment, SyllableFit,
};

/// Neural probabilities are clamped to `[NN_EPS, 1 − NN_EPS]` before the logit.
const NN_EPS: f32 = 1e-6;

fn sigmoid(z: f32) -> f32 {
    1.0 / (1.0 + (-z).exp())
}

fn logit(p: f32) -> f32 {
    let p = p.clamp(NN_EPS, 1.0 - NN_EPS);
    (p / (1.0 - p)).ln()
}

/// Fuses one syllable's acoustic judgement with external evidence into a calibrated probability.
///
/// `logit(p_correct) = β0 + β_ac·llr_target + β_tr·x_tr + β_nn·logit(p_nn)`, where each term is
/// present only if its evidence is:
///
/// - **Acoustic** comes from `fit` alone, and only when its `measured` is not `NotMeasured`. An
///   `Evidence::Acoustic` entry in `external` is ignored, so the acoustic term is never counted twice.
/// - **Transcript** adds `β_tr` when `matched_target` (`x_tr = 1`, else 0) for every entry.
/// - **Neural** adds `β_nn·logit(p_correct)` for every entry, with `p_correct` clamped to
///   `[1e-6, 1 − 1e-6]`.
///
/// A syllable with no contributing evidence gets `sigmoid(β0)` and an empty `basis`. `basis` lists
/// each kind that contributed once, in the order Acoustic, Transcript, Neural.
///
/// A confusion hit on any transcript entry (the first, if there are several) caps `p_correct` at
/// `veto_cap`, sets `heard_as` to the hit's text, and fills `heard` with the hit's tone when the
/// acoustic judgement has none. The cap only lowers `p_correct`.
///
/// `expected`, `distance`, `deltas`, `component` and `measured` are copied from the fit's judgement.
pub fn fuse_syllable(
    fit: &SyllableFit,
    external: &[Evidence],
    w: &FusionWeights,
) -> SyllableAssessment {
    let j = &fit.judgement;
    let mut z = w.beta0;

    let acoustic = !matches!(j.measured, Measured::NotMeasured { .. });
    if acoustic {
        z += w.beta_acoustic * j.llr_target;
    }

    let mut transcript = false;
    let mut neural = false;
    let mut hit: Option<&ConfusionHit> = None;
    for e in external {
        match e {
            Evidence::Acoustic { .. } => {}
            Evidence::Transcript {
                matched_target,
                confusion_hit,
            } => {
                let x_tr = if *matched_target { 1.0 } else { 0.0 };
                z += w.beta_transcript * x_tr;
                transcript = true;
                if hit.is_none() {
                    hit = confusion_hit.as_ref();
                }
            }
            Evidence::Neural { p_correct, .. } => {
                z += w.beta_neural * logit(*p_correct);
                neural = true;
            }
        }
    }

    let mut p_correct = sigmoid(z);
    let mut heard = j.heard.clone();
    let mut heard_as = None;
    if let Some(h) = hit {
        p_correct = p_correct.min(w.veto_cap);
        heard_as = Some(h.text.clone());
        if heard.is_none() {
            heard = Some(h.tone.clone());
        }
    }

    let basis = [
        (acoustic, EvidenceKind::Acoustic),
        (transcript, EvidenceKind::Transcript),
        (neural, EvidenceKind::Neural),
    ]
    .into_iter()
    .filter_map(|(present, kind)| present.then_some(kind))
    .collect();

    SyllableAssessment {
        expected: j.expected.clone(),
        p_correct,
        distance: j.distance,
        heard,
        heard_as,
        deltas: j.deltas.clone(),
        component: j.component.clone(),
        measured: j.measured.clone(),
        basis,
    }
}
