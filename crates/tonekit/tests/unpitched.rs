//! Rulings R102 and R103: a syllable with speech energy and a vowel's spectrum but no pitch (a
//! creaky vowel) is placed and scored on the calibration's unpitched evidence, not left as a miss
//! at a flat prior; noise with no vowel's spectrum (a fricative, a breath) is no syllable.
//!
//! The clips: two voiced syllables (tones 4 and 1, 250 ms, a 110-190 Hz speaker on a warm
//! register) and a third 250 ms stretch of aperiodic noise at the same level, either low-passed
//! (vowel-like: most of its energy below 2 kHz, like a creaky vowel) or white (like a fricative).

use tonekit::{
    analyze, assess, AccentId, AnalyzeOptions, AssessRequest, Candidate, CandidateId,
    GradingTarget, LanguagePack, MeasureIssue, Measured, ToneId, ToneTarget, UtteranceAssessment,
};
use tonekit_testkit::{register_for, synth, SynthSpec, SynthSyllable};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");
const SPEAKER: (f32, f32) = (110.0, 190.0);

/// The shipped calibration with unpitched evidence: tone 3 is unpitched at the end of a phrase
/// far more often than tone 1.
fn with_evidence() -> String {
    let mut calib: serde_json::Value = serde_json::from_str(CMN_CALIB).unwrap();
    let table = serde_json::json!({ "1": -5.0, "2": -3.5, "3": -1.0, "4": -2.5, "5": -3.0 });
    calib["unpitched"] = serde_json::json!({ "phrase_final": table, "other": table });
    calib.to_string()
}

/// Two voiced syllables (4, 1) and then 250 ms of seeded noise, low-passed twice at about 600 Hz
/// when `vowel_like`, at the voiced syllables' RMS.
fn clip(vowel_like: bool) -> Vec<f32> {
    let s = synth(&SynthSpec {
        floor_hz: SPEAKER.0,
        ceil_hz: SPEAKER.1,
        lead_ms: 200.0,
        tail_ms: 0.0,
        syllables: [vec![5.0, 1.0], vec![5.0, 5.0]]
            .into_iter()
            .map(|chao| SynthSyllable {
                chao,
                dur_ms: 250.0,
                gap_after_ms: 60.0,
                unvoiced_onset_ms: 0.0,
                creak: None,
            })
            .collect(),
        snr_db: Some(30.0),
        seed: 1,
    });
    let rms = |x: &[f32]| (x.iter().map(|v| v * v).sum::<f32>() / x.len() as f32).sqrt();
    let voiced = rms(&s.pcm[3200..s.pcm.len() - 960]);
    let mut state = 0x9E37_79B9_7F4A_7C15_u64;
    let mut white = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        (state as f64 / u64::MAX as f64 - 0.5) as f32
    };
    let mut noise: Vec<f32> = (0..4000).map(|_| white()).collect();
    if vowel_like {
        // Two one-pole low-passes at about 600 Hz (a = exp(-2π·600/16000)).
        let a = (-2.0 * std::f32::consts::PI * 600.0 / 16000.0).exp();
        for _ in 0..2 {
            let mut y = 0.0;
            for v in &mut noise {
                y = a * y + (1.0 - a) * *v;
                *v = y;
            }
        }
    }
    let gain = voiced / rms(&noise);
    let mut pcm = s.pcm.clone();
    pcm.extend(noise.iter().map(|v| v * gain));
    pcm.extend(std::iter::repeat_n(0.0, 3200));
    pcm
}

fn reading(tones: &[&str]) -> Candidate {
    Candidate {
        id: CandidateId(tones.join("-")),
        targets: tones
            .iter()
            .map(|t| ToneTarget {
                tone: ToneId((*t).into()),
                lexical_variants: Vec::new(),
                label: None,
            })
            .collect(),
    }
}

fn graded(
    pcm: &[f32],
    calib: Option<&str>,
    intended: &[&str],
    other: &[&str],
) -> UtteranceAssessment {
    let pack = LanguagePack::from_toml(CMN_TOML, calib.or(Some(CMN_CALIB))).unwrap();
    let register = register_for(SPEAKER.0, SPEAKER.1);
    let a = analyze(pcm, 16_000, Some(&register), &AnalyzeOptions::default()).unwrap();
    assert_eq!(a.nuclei.len(), 2, "{:?}", a.nuclei);
    assess(
        &a,
        &pack,
        &AssessRequest {
            grading: GradingTarget {
                accent: AccentId("cmn-standard".into()),
                style: None,
                style_weight: 0.0,
            },
            intended: reading(intended),
            distractors: vec![reading(other)],
            external: Vec::new(),
            compare_accents: Vec::new(),
        },
    )
    .unwrap()
}

fn issues(m: &Measured) -> Vec<MeasureIssue> {
    match m {
        Measured::Partial { issues } => issues.clone(),
        Measured::NotMeasured { issue } => vec![*issue],
        Measured::Full => Vec::new(),
    }
}

#[test]
fn a_vowel_like_stretch_with_no_pitch_is_an_unpitched_syllable() {
    let pcm = clip(true);
    let u = graded(&pcm, None, &["4", "1", "3"], &["4", "1", "1"]);
    let last = &u.syllables[2];
    assert_eq!(
        issues(&last.measured),
        vec![MeasureIssue::Unpitched],
        "{u:#?}"
    );
    assert!(last.distance.is_none());
    // Without unpitched evidence it scores the unvoiced fallback, as a miss would.
    assert!((last.p_correct - 0.0474).abs() < 1e-3, "{}", last.p_correct);
    // The first two are measured on their shapes.
    assert!(u.syllables[..2].iter().all(|s| s.distance.is_some()));
}

#[test]
fn unpitched_evidence_scores_the_tone_creak_points_to() {
    let pcm = clip(true);
    let calib = with_evidence();
    let three = graded(&pcm, Some(&calib), &["4", "1", "3"], &["4", "1", "1"]);
    let one = graded(&pcm, Some(&calib), &["4", "1", "1"], &["4", "1", "3"]);
    let (p3, p1) = (three.syllables[2].p_correct, one.syllables[2].p_correct);
    assert!(p3 > 0.5 && p1 < 0.1, "tone 3 {p3}, tone 1 {p1}");
    assert_eq!(three.intended_rank, 1);
    assert_eq!(one.intended_rank, 2);
    assert_eq!(three.syllables[2].heard, Some(ToneId("3".into())));
}

#[test]
fn noise_without_a_vowel_spectrum_is_no_syllable() {
    let pcm = clip(false);
    let u = graded(
        &pcm,
        Some(&with_evidence()),
        &["4", "1", "3"],
        &["4", "1", "1"],
    );
    assert!(
        u.syllables
            .iter()
            .any(|s| issues(&s.measured) == vec![MeasureIssue::NoNucleus]),
        "{u:#?}"
    );
    assert!(u
        .syllables
        .iter()
        .all(|s| !issues(&s.measured).contains(&MeasureIssue::Unpitched)));
}
