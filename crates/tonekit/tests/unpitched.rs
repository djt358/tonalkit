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

/// The shipped calibration with `phrase_final` and `other` as its unpitched tables.
fn with_tables(phrase_final: serde_json::Value, other: serde_json::Value) -> String {
    let mut calib: serde_json::Value = serde_json::from_str(CMN_CALIB).unwrap();
    calib["unpitched"] = serde_json::json!({ "phrase_final": phrase_final, "other": other });
    calib.to_string()
}

/// The shipped calibration without unpitched evidence.
fn without_evidence() -> String {
    let mut calib: serde_json::Value = serde_json::from_str(CMN_CALIB).unwrap();
    calib.as_object_mut().unwrap().remove("unpitched");
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
    let voiced = rms(&s.pcm[3200..s.pcm.len() - 960]);
    let mut pcm = s.pcm.clone();
    pcm.extend(noise(vowel_like, voiced));
    pcm.extend(std::iter::repeat_n(0.0, 3200));
    pcm
}

fn rms(x: &[f32]) -> f32 {
    (x.iter().map(|v| v * v).sum::<f32>() / x.len() as f32).sqrt()
}

/// 250 ms of seeded noise at RMS `level`, low-passed twice at about 600 Hz when `vowel_like`.
fn noise(vowel_like: bool, level: f32) -> Vec<f32> {
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
    let gain = level / rms(&noise);
    noise.iter().map(|v| v * gain).collect()
}

/// The vowel-like noise alone, between 200 ms silences: a creaky syllable said on its own, or a
/// clip with no pitch anywhere.
fn creak_alone() -> Vec<f32> {
    let mut pcm = vec![0.0; 3200];
    pcm.extend(noise(true, 0.05));
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

/// `pcm` graded with `calib`, or with the compiled-in default calibration (no calibration file,
/// as `Pack.fromToml(calibJson: nil)` gives). The clip must have the two voiced nuclei.
fn graded(
    pcm: &[f32],
    calib: Option<&str>,
    intended: &[&str],
    other: &[&str],
) -> UtteranceAssessment {
    graded_with_nuclei(pcm, calib, intended, other, 2)
}

fn graded_with_nuclei(
    pcm: &[f32],
    calib: Option<&str>,
    intended: &[&str],
    other: &[&str],
    nuclei: usize,
) -> UtteranceAssessment {
    let pack = LanguagePack::from_toml(CMN_TOML, calib).unwrap();
    let register = register_for(SPEAKER.0, SPEAKER.1);
    let a = analyze(pcm, 16_000, Some(&register), &AnalyzeOptions::default()).unwrap();
    assert_eq!(a.nuclei.len(), nuclei, "{:?}", a.nuclei);
    // There is speech: what decides is whether a pitched nucleus anchors the decode.
    assert!(a.speech.is_some());
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
    // The shipped calibration less its unpitched evidence, and the compiled-in default (which
    // has none): either way the syllable is found and nothing decides its tone.
    for calib in [Some(without_evidence()), None] {
        unscored_without_evidence(&pcm, calib.as_deref());
    }
}

fn unscored_without_evidence(pcm: &[f32], calib: Option<&str>) {
    let u = graded(pcm, calib, &["4", "1", "3"], &["4", "1", "1"]);
    let last = &u.syllables[2];
    assert_eq!(
        last.measured,
        Measured::NotMeasured {
            issue: MeasureIssue::Unpitched
        },
        "{u:#?}"
    );
    assert!(last.distance.is_none());
    // Without unpitched evidence nothing about its tone was measured, so the reading is not
    // scored (rulings R103, R104): a prior decides nothing.
    assert_eq!(u.overall, None);
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
    // A syllable nothing could hold leaves the reading unscored (ruling R104).
    assert_eq!(u.overall, None);
}

#[test]
fn an_isolated_or_all_unpitched_clip_never_reaches_the_unpitched_evidence() {
    // The decoder anchors syllables only once the analysis has a pitched nucleus (`search` gives
    // up without one), so a creaky syllable said on its own, or a clip with no pitch anywhere, is
    // `NotMeasured { Unvoiced }` and unscored even with unpitched evidence (spec §7.2, R103).
    let pcm = creak_alone();
    let calib = with_evidence();
    for (intended, other) in [(&["3"][..], &["1"][..]), (&["3", "4"][..], &["1", "1"][..])] {
        let u = graded_with_nuclei(&pcm, Some(&calib), intended, other, 0);
        assert_eq!(u.syllables.len(), intended.len());
        assert!(
            u.syllables.iter().all(|s| s.measured
                == Measured::NotMeasured {
                    issue: MeasureIssue::Unvoiced
                }),
            "{u:#?}"
        );
        assert_eq!(u.overall, None);
    }
}

#[test]
fn a_table_that_rates_every_tone_alike_is_no_evidence() {
    // Ruling R119: a pooled place gives every tone LLR 0, which tells the tones apart no better
    // than no table, so the syllable is `NotMeasured { Unpitched }` and the reading unscored. The
    // shipped calibration pools both places; so does any table with one rate for every tone.
    let pcm = clip(true);
    let flat = serde_json::json!({ "1": -1.0, "2": -1.0, "3": -1.0, "4": -1.0, "5": -1.0 });
    for calib in [CMN_CALIB.to_owned(), with_tables(flat.clone(), flat)] {
        unscored_without_evidence(&pcm, Some(&calib));
    }
}

#[test]
fn a_table_that_tells_the_tones_apart_at_the_syllables_place_still_scores() {
    // Place by place: a flat table elsewhere in the phrase does not stop the phrase-final one,
    // which differs, from scoring the last syllable.
    let pcm = clip(true);
    let differs = serde_json::json!({ "1": -5.0, "2": -3.5, "3": -1.0, "4": -2.5, "5": -3.0 });
    let flat = serde_json::json!({ "1": -3.6, "2": -3.6, "3": -3.6, "4": -3.6, "5": -3.6 });
    let u = graded(
        &pcm,
        Some(&with_tables(differs, flat)),
        &["4", "1", "3"],
        &["4", "1", "1"],
    );
    let last = &u.syllables[2];
    assert_eq!(
        last.measured,
        Measured::Partial {
            issues: vec![MeasureIssue::Unpitched]
        },
        "{u:#?}"
    );
    assert!(last.p_correct > 0.5, "{u:#?}");
    assert!(u.overall.is_some(), "{u:#?}");
}
