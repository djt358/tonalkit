//! Regressions in the shipped `packs/cmn` pack data, checked through the facade on synthetic
//! speech (spec §6, §7).
//!
//! R47: in a non-final position a learner's full-dip third tone (Chao 2-1-4) fits the second tone
//! better than the pack's half-third `[2, 1]`, so a T3-for-T2 error used to be accepted. The
//! `cmn-standard` non-final T3 is now a mixture that also expects the full dip at low weight
//! (0.25; the half-third keeps 0.75).
//!
//! The margins below are deliberately modest (R48). At the seed calibration the posteriors are
//! compressed: a perfect synthetic T1 scores only about 0.71 with a cold register, so a clip's
//! `overall` (the minimum over its syllables) has little room to fall, and the T3-for-T2 error's
//! middle syllable still scores above 0.5. What is pinned is the direction of the fix and that
//! the intended-T3 side keeps its credit; the absolute sharpness belongs to the P1 calibration,
//! and the mixture weight is not to be tuned on synthetic audio.

use tonekit::{
    analyze, assess, AccentId, AnalyzeOptions, AssessRequest, Candidate, CandidateId,
    GradingTarget, LanguagePack, Register, ToneId, ToneTarget,
};
use tonekit_testkit::{synth, SynthSpec, SynthSyllable};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");

const RATE: u32 = 16_000;

/// The speaker of the harness's synthetic corpus (`tests/support.py`): harmonic voice, floor
/// 100 Hz / ceiling 200 Hz, 250 ms syllables, 150 ms gaps, 300 ms of silence either side. Unlike
/// the facade's own tests, a `"3"` is spoken as the full dip, wherever it stands; `"3h"` is the
/// half-third (Chao 2-1) for the clips that need one.
fn spoken_tones(tones: &[&str]) -> Vec<f32> {
    let knots = |tone: &str| match tone {
        "1" => vec![5.0, 5.0],
        "2" => vec![3.0, 5.0],
        "3" => vec![2.0, 1.0, 4.0],
        "3h" => vec![2.0, 1.0],
        "4" => vec![5.0, 1.0],
        other => panic!("no spoken form for tone {other}"),
    };
    let last = tones.len() - 1;
    synth(&SynthSpec {
        floor_hz: 100.0,
        ceil_hz: 200.0,
        lead_ms: 300.0,
        tail_ms: 300.0,
        syllables: tones
            .iter()
            .enumerate()
            .map(|(i, t)| SynthSyllable {
                chao: knots(t),
                dur_ms: 250.0,
                gap_after_ms: if i == last { 0.0 } else { 150.0 },
                unvoiced_onset_ms: 0.0,
                creak: None,
            })
            .collect(),
        snr_db: None,
        seed: 0,
    })
    .pcm
}

/// Grades `intended` on the clip speaking `produced`: the real cmn pack, `cmn-standard`, no
/// distractors, analysed with `register` (`None`: cold start). Returns
/// `(overall, p_correct per syllable)`.
fn grade(produced: &[&str], intended: &[&str], register: Option<&Register>) -> (f32, Vec<f32>) {
    let pack = LanguagePack::from_toml(CMN_TOML, Some(CMN_CALIB)).unwrap();
    let analysis = analyze(
        &spoken_tones(produced),
        RATE,
        register,
        &AnalyzeOptions::default(),
    )
    .unwrap();
    let request = AssessRequest {
        grading: GradingTarget {
            accent: AccentId("cmn-standard".into()),
            style: None,
            style_weight: 0.0,
        },
        intended: Candidate {
            id: CandidateId("spell".into()),
            targets: intended
                .iter()
                .map(|t| ToneTarget {
                    tone: ToneId((*t).into()),
                    lexical_variants: Vec::new(),
                    label: None,
                })
                .collect(),
        },
        distractors: Vec::new(),
        external: Vec::new(),
        compare_accents: Vec::new(),
    };
    let r = assess(&analysis, &pack, &request).unwrap();
    (
        r.overall.expect("a clean clip is measured"),
        r.syllables.iter().map(|s| s.p_correct).collect(),
    )
}

#[test]
fn a_full_dip_third_tone_is_graded_below_a_second_tone_in_non_final_position() {
    // Gate pair 02 (intended 1-2-4), cold register: the T3-for-T2 error must score clearly below
    // the correct clip. Before R47 the two were 0.004 apart.
    let (correct, correct_p) = grade(&["1", "2", "4"], &["1", "2", "4"], None);
    let (error, error_p) = grade(&["1", "3", "4"], &["1", "2", "4"], None);
    eprintln!("R47 gate-02: correct {correct:.4} {correct_p:.4?}, error {error:.4} {error_p:.4?}");
    assert!(
        error <= correct - 0.03,
        "error overall {error:.4} is not 0.03 below correct overall {correct:.4}"
    );
}

#[test]
fn an_intended_third_tone_keeps_its_credit_for_the_full_dip() {
    // The other direction: a learner asked for a T3 who over-produces it as the full dip in a
    // non-final position is not punished (the old pack scored this middle syllable 0.63).
    let (overall, p) = grade(&["1", "3", "4"], &["1", "3", "4"], None);
    eprintln!("R47 intended 1-3-4, produced 1-3-4: overall {overall:.4} {p:.4?}");
    assert!(p[1] > 0.65, "intended T3 middle p_correct {:.4}", p[1]);
}

#[test]
fn a_second_tone_for_an_intended_non_final_third_tone_still_scores_far_below_the_half_third() {
    // The reverse trade of R47: widening the expected non-final T3 with the full dip could let a
    // T2 pass for an intended T3. Intended 1-3-4, cold register: the T2-for-T3 error must stay
    // well below the correct clip spoken with the standard half-third middle. (Measured with the
    // old pack: error 0.069 against correct 0.723; with the R47 pack: 0.273 against 0.723.)
    let (error, error_p) = grade(&["1", "2", "4"], &["1", "3", "4"], None);
    let (correct, correct_p) = grade(&["1", "3h", "4"], &["1", "3", "4"], None);
    eprintln!("R47 reverse: error {error:.4} {error_p:.4?}, correct half-third {correct:.4} {correct_p:.4?}");
    assert!(
        error <= correct - 0.03,
        "T2-for-T3 error overall {error:.4} is not 0.03 below the correct half-third overall {correct:.4}"
    );
}
