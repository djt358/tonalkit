//! Ruling R108: a syllable whose pitch gives way to creak (speech with a vowel's spectrum and no
//! pitch right after its last pitched frame) is flagged `CreakyTail`, and the calibration's
//! creaky-tail evidence moves its tone towards the tones that end in creak.
//!
//! The clip: a tone 1 (250 ms) and then a short fall (120 ms, Chao 5 to 3) running straight into
//! 150 ms of aperiodic noise low-passed like a vowel, at the voiced syllables' level: a phrase-final
//! tone 4 whose end went creaky, as a high voice's often does.

use tonekit::{
    analyze, assess, AccentId, AnalyzeOptions, AssessRequest, Candidate, CandidateId,
    GradingTarget, LanguagePack, MeasureIssue, Measured, ToneId, ToneTarget, UtteranceAssessment,
};
use tonekit_testkit::{register_for, synth, SynthSpec, SynthSyllable};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");
const SPEAKER: (f32, f32) = (110.0, 190.0);

/// The shipped calibration with creaky-tail evidence (tone 4 ends in creak at the end of a phrase
/// far more often than tone 1), or with none.
fn calib(evidence: bool) -> String {
    let mut calib: serde_json::Value = serde_json::from_str(CMN_CALIB).unwrap();
    let map = calib.as_object_mut().unwrap();
    if evidence {
        let table = serde_json::json!({ "1": -4.0, "2": -1.5, "3": -0.7, "4": -0.2, "5": -2.0 });
        map.insert(
            "creaky_tail".into(),
            serde_json::json!({ "phrase_final": table, "other": table }),
        );
    } else {
        map.remove("creaky_tail");
    }
    calib.to_string()
}

/// The two syllables, then (when `creaky`) 150 ms of seeded noise low-passed twice at about
/// 600 Hz at the voiced syllables' RMS, or as much silence.
fn clip(creaky: bool) -> Vec<f32> {
    let s = synth(&SynthSpec {
        floor_hz: SPEAKER.0,
        ceil_hz: SPEAKER.1,
        lead_ms: 200.0,
        tail_ms: 0.0,
        syllables: vec![
            SynthSyllable {
                chao: vec![5.0, 5.0],
                dur_ms: 250.0,
                gap_after_ms: 60.0,
                unvoiced_onset_ms: 0.0,
                creak: None,
            },
            SynthSyllable {
                chao: vec![5.0, 3.0],
                dur_ms: 120.0,
                gap_after_ms: 0.0,
                unvoiced_onset_ms: 0.0,
                creak: None,
            },
        ],
        snr_db: Some(30.0),
        seed: 3,
    });
    let rms = |x: &[f32]| (x.iter().map(|v| v * v).sum::<f32>() / x.len() as f32).sqrt();
    let voiced = rms(&s.pcm[3200..]);
    let mut state = 0x9E37_79B9_7F4A_7C15_u64;
    let mut white = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        (state as f64 / u64::MAX as f64 - 0.5) as f32
    };
    let mut noise: Vec<f32> = (0..2400).map(|_| white()).collect();
    let a = (-2.0 * std::f32::consts::PI * 600.0 / 16000.0).exp();
    for _ in 0..2 {
        let mut y = 0.0;
        for v in &mut noise {
            y = a * y + (1.0 - a) * *v;
            *v = y;
        }
    }
    let gain = if creaky { voiced / rms(&noise) } else { 0.0 };
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

fn graded(pcm: &[f32], calib: &str, intended: &[&str], other: &[&str]) -> UtteranceAssessment {
    let pack = LanguagePack::from_toml(CMN_TOML, Some(calib)).unwrap();
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

fn has_tail(m: &Measured) -> bool {
    matches!(m, Measured::Partial { issues } if issues.contains(&MeasureIssue::CreakyTail))
}

#[test]
fn a_pitch_that_runs_into_a_vowel_with_no_pitch_has_a_creaky_tail() {
    let u = graded(&clip(true), &calib(false), &["1", "4"], &["1", "1"]);
    assert!(has_tail(&u.syllables[1].measured), "{u:#?}");
    assert!(!has_tail(&u.syllables[0].measured), "{u:#?}");
    assert!(u.syllables.iter().all(|s| s.distance.is_some()));
    // The same syllables ending in silence have no tail.
    let clean = graded(&clip(false), &calib(false), &["1", "4"], &["1", "1"]);
    assert!(
        clean.syllables.iter().all(|s| !has_tail(&s.measured)),
        "{clean:#?}"
    );
}

#[test]
fn creaky_tail_evidence_favours_the_tones_that_creak() {
    let pcm = clip(true);
    let (with, without) = (calib(true), calib(false));
    let four = |c: &str| graded(&pcm, c, &["1", "4"], &["1", "1"]).syllables[1].p_correct;
    let one = |c: &str| graded(&pcm, c, &["1", "1"], &["1", "4"]).syllables[1].p_correct;
    assert!(
        four(&with) > four(&without),
        "{} vs {}",
        four(&with),
        four(&without)
    );
    assert!(
        one(&with) < one(&without),
        "{} vs {}",
        one(&with),
        one(&without)
    );
    // Evidence changes nothing for a syllable without a tail.
    let clean = clip(false);
    let p = |c: &str| graded(&clean, c, &["1", "4"], &["1", "1"]).syllables[1].p_correct;
    assert_eq!(p(&with), p(&without));
}
