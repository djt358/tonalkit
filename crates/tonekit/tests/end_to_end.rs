//! The facade end to end: synthetic speech in, `UtteranceAssessment` out (spec §4.1, §10, §12).
//!
//! Tones are spoken as ruling R8 fixes them: "1" → [5,5], "2" → [3,5], "3" → [2,1,4] when
//! phrase-final and [2,1] otherwise, "4" → [5,1]; 250 ms syllables with 60 ms gaps, floor 100 Hz /
//! ceiling 200 Hz.

use approx::assert_abs_diff_eq;
use tonekit::{
    analyze, assess, decode, lattice, AccentId, Analysis, AnalyzeOptions, AssessError,
    AssessRequest, Candidate, CandidateId, Evidence, F0Choice, F0Frame, F0Track, GradingTarget,
    LanguagePack, MeasureIssue, Measured, Register, RegisterSource, ToneId, ToneTarget,
    UtteranceAssessment,
};
use tonekit_testkit::{register_for, synth, Synth, SynthSpec, SynthSyllable};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");

const RATE: u32 = 16_000;

fn cmn() -> LanguagePack {
    LanguagePack::from_toml(CMN_TOML, Some(CMN_CALIB)).unwrap()
}

fn accent(id: &str) -> AccentId {
    AccentId(id.into())
}

fn std_g() -> GradingTarget {
    GradingTarget {
        accent: accent("cmn-standard"),
        style: None,
        style_weight: 0.0,
    }
}

/// A candidate whose targets carry no lexical variants or labels.
fn c(id: &str, tones: &[&str]) -> Candidate {
    Candidate {
        id: CandidateId(id.into()),
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

fn intended(tones: &[&str]) -> Candidate {
    c("spell", tones)
}

/// Chao knots of a spoken tone; a third tone dips and rises only when phrase-final.
fn knots(tone: &str, last: bool) -> Vec<f32> {
    match tone {
        "1" => vec![5.0, 5.0],
        "2" => vec![3.0, 5.0],
        "3" if last => vec![2.0, 1.0, 4.0],
        "3" => vec![2.0, 1.0],
        "4" => vec![5.0, 1.0],
        other => panic!("no spoken form for tone {other}"),
    }
}

/// One 250 ms syllable per tone, 60 ms of silence after each, floor 100 Hz / ceiling 200 Hz,
/// 200 ms lead and tail, seed 1; each syllable opens with `onset_ms(250.0)` ms of unvoiced noise.
fn spec_of(tones: &[&str], onset_ms: impl Fn(f32) -> f32) -> SynthSpec {
    SynthSpec {
        floor_hz: 100.0,
        ceil_hz: 200.0,
        lead_ms: 200.0,
        tail_ms: 200.0,
        syllables: tones
            .iter()
            .enumerate()
            .map(|(i, t)| SynthSyllable {
                chao: knots(t, i + 1 == tones.len()),
                dur_ms: 250.0,
                gap_after_ms: 60.0,
                unvoiced_onset_ms: onset_ms(250.0),
                creak: None,
            })
            .collect(),
        snr_db: None,
        seed: 1,
    }
}

fn spoken(tones: &[&str]) -> Synth {
    synth(&spec_of(tones, |_| 0.0))
}

/// The same syllables with every one all noise: no f0 at all.
fn whispered(tones: &[&str]) -> Synth {
    synth(&spec_of(tones, |dur_ms| dur_ms))
}

fn req(tones: &[&str]) -> AssessRequest {
    AssessRequest {
        grading: std_g(),
        intended: intended(tones),
        distractors: Vec::new(),
        external: Vec::new(),
        compare_accents: Vec::new(),
    }
}

/// The speaker's exact, warm register (n = 100).
fn warm() -> Register {
    register_for(100.0, 200.0)
}

/// `s` analysed with pYIN under `register`.
fn analysis_of(s: &Synth, register: Option<&Register>) -> Analysis {
    analyze(&s.pcm, RATE, register, &AnalyzeOptions::default()).unwrap()
}

/// `tones` spoken and analysed with the speaker's warm register.
fn warm_analysis(tones: &[&str]) -> Analysis {
    analysis_of(&spoken(tones), Some(&warm()))
}

/// Analyses `s` with the speaker's warm register and grades `intended`.
fn assess_of(s: &Synth, intended: Candidate) -> UtteranceAssessment {
    let request = AssessRequest {
        intended,
        ..req(&[])
    };
    assess(&analysis_of(s, Some(&warm())), &cmn(), &request).unwrap()
}

/// Ground-truth f0 as a track, for the external-provider path.
fn truth_track(s: &Synth) -> F0Track {
    F0Track {
        frames: s
            .f0_truth
            .iter()
            .map(|hz| F0Frame {
                hz: *hz,
                voiced_p: if hz.is_some() { 1.0 } else { 0.0 },
            })
            .collect(),
        provider: "truth".into(),
    }
}

fn external(track: F0Track) -> AnalyzeOptions {
    AnalyzeOptions {
        f0: F0Choice::External(track),
    }
}

fn all_not_measured(r: &UtteranceAssessment) -> bool {
    r.syllables
        .iter()
        .all(|s| matches!(s.measured, Measured::NotMeasured { .. }))
}

// ---- grading ------------------------------------------------------------------------------

#[test]
fn assess_correct_vs_single_tone_error() {
    let ok = assess_of(&spoken(&["4", "1", "3"]), intended(&["4", "1", "3"]));
    let bad = assess_of(&spoken(&["4", "1", "4"]), intended(&["4", "1", "3"]));
    let (ok, bad) = (ok.overall.unwrap(), bad.overall.unwrap());
    // Thresholds per ruling R9. Observed on these utterances: correct 0.766, wrong 0.003.
    assert!(ok > 0.6, "correct overall {ok}");
    assert!(bad < 0.3, "wrong overall {bad}");
    assert!(ok - bad > 0.4, "gap {}", ok - bad);
}

#[test]
fn assessment_reports_the_intended_reading_first() {
    let ok = assess_of(&spoken(&["4", "1", "3"]), intended(&["4", "1", "3"]));
    assert_eq!(ok.schema, "tonekit.assessment.v1");
    assert_eq!(ok.intended, CandidateId("spell".into()));
    assert_eq!(ok.intended_rank, 1);
    // R37: the margin is against the null's biased score (`null_llr + null_bias`), so a correct
    // reading with no distractors is clearly ahead of "something else was said". Observed 1.97
    // (the raw-null margin was -0.03).
    assert!(ok.margin_llr > 0.0, "margin {}", ok.margin_llr);
    let expected: Vec<&str> = ok.syllables.iter().map(|s| s.expected.0.as_str()).collect();
    assert_eq!(expected, ["4", "1", "3"]);
}

#[test]
fn a_better_distractor_outranks_the_intended_reading() {
    let a = warm_analysis(&["4", "1", "4"]);
    let request = AssessRequest {
        distractors: vec![c("said", &["4", "1", "4"])],
        ..req(&["4", "1", "3"])
    };
    let r = assess(&a, &cmn(), &request).unwrap();
    assert_eq!(r.intended_rank, 2);
    assert!(r.margin_llr < 0.0, "margin {}", r.margin_llr);
}

#[test]
fn every_number_in_an_assessment_is_finite() {
    // Ruling R12. A wrong tone exercises deltas and distance as well as the plain path.
    let a = warm_analysis(&["4", "1", "4"]);
    let request = AssessRequest {
        compare_accents: vec![accent("cmn-standard"), accent("cmn-TW")],
        ..req(&["4", "1", "3"])
    };
    let r = assess(&a, &cmn(), &request).unwrap();
    assert!(r.overall.is_some_and(f32::is_finite));
    assert!(r.margin_llr.is_finite());
    for s in &r.syllables {
        assert!(s.p_correct.is_finite() && (0.0..=1.0).contains(&s.p_correct));
        assert!(s.distance.is_none_or(f32::is_finite));
        assert!(s.deltas.iter().all(|d| d.amount.is_finite()));
    }
    assert!(r.accent_fit.iter().all(|f| f.llr.is_finite()));
    let reg = &r.register_update;
    assert!([reg.floor_st, reg.median_st, reg.ceil_st]
        .iter()
        .all(|x| x.is_finite()));
}

// ---- issues and registers ---------------------------------------------------------------

#[test]
fn whisper_is_not_measured() {
    // Review Focus 2.
    let a = analysis_of(&whispered(&["4", "1", "3"]), None);
    let r = assess(&a, &cmn(), &req(&["4", "1", "3"])).unwrap();
    assert!(r.overall.is_none());
    assert_eq!(r.syllables.len(), 3);
    assert!(all_not_measured(&r));
}

#[test]
fn silence_is_not_measured_either() {
    let a = analyze(&[0.0; 16_000], RATE, None, &AnalyzeOptions::default()).unwrap();
    assert!(a.speech.is_none() && a.nuclei.is_empty() && a.boundaries.is_empty());
    let r = assess(&a, &cmn(), &req(&["4", "1", "3"])).unwrap();
    assert!(r.overall.is_none());
    assert!(all_not_measured(&r));
}

#[test]
fn cold_start_register_flags_and_widens() {
    // Review Focus 1.
    let a = analysis_of(&spoken(&["4", "1", "3"]), None);
    assert_eq!(a.register_source, RegisterSource::ColdStart);
    assert!(a.issues.contains(&MeasureIssue::ColdStartRegister));
    assert_eq!(tonekit_pack::widen_for(&a.issues), 1.5);
    // The register is the utterance's own, counting the syllables heard.
    let r = &a.register;
    assert_eq!(r.n_syllables, 3);
    assert!(r.floor_st < r.median_st && r.median_st < r.ceil_st);
}

#[test]
fn a_given_register_is_used_as_it_is() {
    let a = warm_analysis(&["4", "1", "3"]);
    assert_eq!(a.register_source, RegisterSource::Given);
    assert_eq!(a.register, warm());
    assert!(!a.issues.contains(&MeasureIssue::ColdStartRegister));
    assert_eq!(tonekit_pack::widen_for(&a.issues), 1.0);
}

#[test]
fn a_given_register_that_is_still_cold_is_flagged() {
    let cold = Register {
        n_syllables: 12,
        ..warm()
    };
    let a = analysis_of(&spoken(&["4", "1", "3"]), Some(&cold));
    assert_eq!(a.register_source, RegisterSource::Given);
    assert_eq!(a.register, cold);
    assert!(a.issues.contains(&MeasureIssue::ColdStartRegister));
}

#[test]
fn clipped_input_is_flagged() {
    let clipped: Vec<f32> = spoken(&["4", "1", "3"])
        .pcm
        .iter()
        .map(|x| (x * 4.0).clamp(-1.0, 1.0))
        .collect();
    let a = analyze(&clipped, RATE, Some(&warm()), &AnalyzeOptions::default()).unwrap();
    assert!(a.issues.contains(&MeasureIssue::Clipped));
    assert_eq!(tonekit_pack::widen_for(&a.issues), 1.5);
    // Clean audio is flagged for neither Clipped nor LowSnr.
    let clean = warm_analysis(&["4", "1", "3"]);
    assert!(clean.issues.is_empty(), "{:?}", clean.issues);
}

#[test]
fn a_flat_noise_floor_is_flagged_low_snr() {
    // Speech at 0 dB over a steady hum: p95 - p10 of the frame energies stays under 10 dB.
    let s = synth(&SynthSpec {
        snr_db: Some(0.0),
        ..spec_of(&["4", "1", "3"], |_| 0.0)
    });
    let a = analysis_of(&s, Some(&warm()));
    assert!(a.issues.contains(&MeasureIssue::LowSnr), "{:?}", a.issues);
}

// ---- snapshot ---------------------------------------------------------------------------

/// Rounds every float in `v` to 3 decimal places, so the snapshot survives last-bit noise.
fn round3(v: serde_json::Value) -> serde_json::Value {
    use serde_json::{Number, Value};
    match v {
        Value::Number(n) if n.is_f64() => {
            let x = (n.as_f64().unwrap() * 1000.0).round() / 1000.0;
            // -0.0 and 0.0 are one number here.
            Number::from_f64(if x == 0.0 { 0.0 } else { x }).map_or(Value::Null, Value::Number)
        }
        Value::Array(items) => Value::Array(items.into_iter().map(round3).collect()),
        Value::Object(map) => Value::Object(map.into_iter().map(|(k, v)| (k, round3(v))).collect()),
        other => other,
    }
}

#[test]
fn assessment_snapshot() {
    let r = assess_of(&spoken(&["4", "1", "3"]), intended(&["4", "1", "3"]));
    insta::assert_json_snapshot!(round3(serde_json::to_value(&r).unwrap()));
}

// ---- input checks -----------------------------------------------------------------------

#[test]
fn rejects_wrong_rate_and_empty() {
    assert!(matches!(
        analyze(&[0.0; 100], 44_100, None, &Default::default()),
        Err(AssessError::UnsupportedSampleRate { got: 44_100 })
    ));
    assert!(matches!(
        analyze(&[], 16_000, None, &Default::default()),
        Err(AssessError::EmptyAudio)
    ));
}

#[test]
fn audio_shorter_than_a_frame_is_analysed_as_silence() {
    let a = analyze(&[0.0; 10], RATE, None, &AnalyzeOptions::default()).unwrap();
    assert_eq!(a.f0.frames.len(), 1);
    assert_eq!(a.energy.db.len(), 1);
    assert!(a.speech.is_none());
}

#[test]
fn non_finite_samples_do_not_panic() {
    let mut pcm = spoken(&["4", "1", "3"]).pcm;
    pcm[8_000] = f32::NAN;
    pcm[8_001] = f32::INFINITY;
    let a = analyze(&pcm, RATE, Some(&warm()), &AnalyzeOptions::default()).unwrap();
    assert!(a.energy.db.iter().all(|d| d.is_finite()));
}

// ---- external f0 ------------------------------------------------------------------------

#[test]
fn external_f0_track_is_used() {
    let s = spoken(&["4", "1", "3"]);
    let ext = analyze(&s.pcm, RATE, Some(&warm()), &external(truth_track(&s))).unwrap();
    assert_eq!(ext.f0.provider, "external");
    assert_eq!(ext.f0.frames.len(), s.pcm.len() / 160 + 1);
    let pyin = analysis_of(&s, Some(&warm()));
    assert_eq!(pyin.f0.provider, "pyin");

    let request = req(&["4", "1", "3"]);
    let overall_ext = assess(&ext, &cmn(), &request).unwrap().overall.unwrap();
    let overall_pyin = assess(&pyin, &cmn(), &request).unwrap().overall.unwrap();
    assert!((overall_ext - overall_pyin).abs() < 0.2);
}

#[test]
fn an_external_track_of_the_wrong_length_is_fitted() {
    let s = spoken(&["4", "1", "3"]);
    let frames = s.pcm.len() / 160 + 1;
    let mut short = truth_track(&s);
    short.frames.truncate(frames - 7);
    let mut long = truth_track(&s);
    long.frames.extend(std::iter::repeat_n(
        F0Frame {
            hz: None,
            voiced_p: 0.0,
        },
        9,
    ));
    for track in [short, long] {
        let a = analyze(&s.pcm, RATE, Some(&warm()), &external(track)).unwrap();
        assert_eq!(a.f0.frames.len(), frames);
        assert_eq!(a.f0.provider, "external");
    }
}

#[test]
fn an_external_octave_error_is_repaired() {
    let s = spoken(&["1", "1", "1"]);
    let mut track = truth_track(&s);
    // One frame in the middle of the first syllable reads an octave low.
    let at = track.frames.iter().position(|f| f.hz.is_some()).unwrap() + 12;
    let good = track.frames[at].hz.unwrap();
    track.frames[at].hz = Some(good / 2.0);
    let a = analyze(&s.pcm, RATE, Some(&warm()), &external(track)).unwrap();
    assert_abs_diff_eq!(a.f0.frames[at].hz.unwrap(), good, epsilon = 0.01);
}

/// An external track is untrusted input at the FFI boundary (ruling R43): a hostile or buggy
/// pitch model may report NaN, negative or infinite Hz and a NaN confidence. `analyze` cleans it
/// before anything reads it, so nothing downstream sees a non-finite number or panics.
#[test]
fn a_hostile_external_track_is_sanitised() {
    let s = spoken(&["4", "1", "3"]);
    let mut track = truth_track(&s);
    let voiced: Vec<usize> = track
        .frames
        .iter()
        .enumerate()
        .filter_map(|(i, f)| f.hz.map(|_| i))
        .collect();
    let (nan_hz, negative_hz, infinite_hz, nan_p, big_p, negative_p) = (
        voiced[3], voiced[8], voiced[14], voiced[20], voiced[26], voiced[32],
    );
    track.frames[nan_hz].hz = Some(f32::NAN);
    track.frames[negative_hz].hz = Some(-5.0);
    track.frames[infinite_hz].hz = Some(f32::INFINITY);
    track.frames[nan_p].voiced_p = f32::NAN;
    track.frames[big_p].voiced_p = 7.0;
    track.frames[negative_p].voiced_p = f32::NEG_INFINITY;
    // A zero and a negative infinity in unvoiced-looking frames too.
    let unvoiced = track.frames.iter().position(|f| f.hz.is_none()).unwrap();
    track.frames[unvoiced].hz = Some(0.0);
    track.frames[unvoiced + 1].hz = Some(f32::NEG_INFINITY);

    let a = analyze(&s.pcm, RATE, Some(&warm()), &external(track)).unwrap();

    // The offending frames become unvoiced; confidences are finite and inside [0, 1].
    for i in [nan_hz, negative_hz, infinite_hz, unvoiced, unvoiced + 1] {
        assert_eq!(a.f0.frames[i].hz, None, "frame {i}");
    }
    assert_eq!(a.f0.frames[nan_p].voiced_p, 0.0);
    assert_eq!(a.f0.frames[big_p].voiced_p, 1.0);
    assert_eq!(a.f0.frames[negative_p].voiced_p, 0.0);
    assert!(a.f0.frames.iter().all(|f| {
        f.hz.is_none_or(|hz| hz.is_finite() && hz > 0.0)
            && f.voiced_p.is_finite()
            && (0.0..=1.0).contains(&f.voiced_p)
    }));
    assert!(a.voiced_st.iter().all(|st| st.is_finite()));

    // R12 through the whole pipeline: every number that comes out is finite.
    let request = AssessRequest {
        compare_accents: vec![accent("cmn-standard"), accent("cmn-TW")],
        ..req(&["4", "1", "3"])
    };
    let r = assess(&a, &cmn(), &request).unwrap();
    assert!(r.overall.is_some_and(f32::is_finite));
    assert!(r.margin_llr.is_finite());
    for syllable in &r.syllables {
        assert!(syllable.p_correct.is_finite() && (0.0..=1.0).contains(&syllable.p_correct));
        assert!(syllable.distance.is_none_or(f32::is_finite));
        assert!(syllable.deltas.iter().all(|d| d.amount.is_finite()));
    }
    assert!(r.accent_fit.iter().all(|f| f.llr.is_finite()));
    let reg = &r.register_update;
    assert!([reg.floor_st, reg.median_st, reg.ceil_st]
        .iter()
        .all(|x| x.is_finite()));
    // The clean frames around the damage still carry the utterance: it is graded, not dropped.
    assert!(!all_not_measured(&r));
}

// ---- accent fit -------------------------------------------------------------------------

#[test]
fn accent_fit_only_for_requested_accents() {
    let a = warm_analysis(&["4", "1", "3"]);
    let pack = cmn();
    let mut request = req(&["4", "1", "3"]);

    request.compare_accents = vec![accent("cmn-standard"), accent("cmn-TW")];
    let r = assess(&a, &pack, &request).unwrap();
    let fit: Vec<(&str, f32)> = r
        .accent_fit
        .iter()
        .map(|f| (f.accent.0.as_str(), f.llr))
        .collect();
    assert_eq!(fit.len(), 2);
    assert_eq!(fit[0].0, "cmn-standard");
    assert_eq!(fit[1].0, "cmn-TW");
    assert!(fit.iter().all(|(_, llr)| llr.is_finite()));
    // Graded under the same accent, the intended candidate's llr is the decode's own.
    let direct = decode(&a, &pack, &std_g(), &[intended(&["4", "1", "3"])]).unwrap();
    assert_abs_diff_eq!(fit[0].1, direct.candidates[0].llr, epsilon = 1e-4);

    request.compare_accents = Vec::new();
    assert!(assess(&a, &pack, &request).unwrap().accent_fit.is_empty());
}

#[test]
fn comparing_an_unknown_accent_is_a_pack_error() {
    let a = warm_analysis(&["4", "1", "3"]);
    let request = AssessRequest {
        compare_accents: vec![accent("cmn-Atlantis")],
        ..req(&["4", "1", "3"])
    };
    assert!(matches!(
        assess(&a, &cmn(), &request),
        Err(AssessError::Pack { .. })
    ));
}

// ---- register update --------------------------------------------------------------------

#[test]
fn register_update_merges_given_register() {
    let given = Register {
        n_syllables: 40,
        ..warm()
    };
    let a = analysis_of(&spoken(&["4", "1", "3"]), Some(&given));
    let r = assess(&a, &cmn(), &req(&["4", "1", "3"])).unwrap();
    assert_eq!(r.register_update.n_syllables, 43);
    // The merge moved it (this utterance's p5/p50/p95 are not the speaker's exact floor/ceil).
    assert_ne!(r.register_update.floor_st, given.floor_st);
    // w = min(0.5, 3/43): a small step.
    assert!((r.register_update.median_st - given.median_st).abs() < 1.0);
}

#[test]
fn register_update_of_a_cold_start_is_the_cold_register_itself() {
    let a = analysis_of(&spoken(&["4", "1", "3"]), None);
    let r = assess(&a, &cmn(), &req(&["4", "1", "3"])).unwrap();
    // Never merged with the utterance it was estimated from.
    assert_eq!(r.register_update, a.register);
}

#[test]
fn a_whispered_cast_leaves_a_given_register_unchanged() {
    // R38: nothing was measured, so u = 0 and not even n_syllables moves.
    let given = Register {
        n_syllables: 40,
        ..warm()
    };
    let a = analysis_of(&whispered(&["4", "1", "3"]), Some(&given));
    let r = assess(&a, &cmn(), &req(&["4", "1", "3"])).unwrap();
    assert!(all_not_measured(&r));
    assert_eq!(r.register_update, given);
}

#[test]
fn a_whispered_cold_start_leaves_nothing_to_persist() {
    // R38: the fallback register, with n_syllables 0, which consumers do not persist.
    let a = analysis_of(&whispered(&["4", "1", "3"]), None);
    let r = assess(&a, &cmn(), &req(&["4", "1", "3"])).unwrap();
    assert!(all_not_measured(&r));
    assert_eq!(r.register_update.n_syllables, 0);
    assert_eq!(r.register_update, a.register);
}

#[test]
fn only_measured_syllables_count_toward_the_register_update() {
    let given = Register {
        n_syllables: 40,
        ..warm()
    };
    let a = analysis_of(&spoken(&["4", "1", "3"]), Some(&given));
    let r = assess(&a, &cmn(), &req(&["4", "1", "3"])).unwrap();
    let measured = r
        .syllables
        .iter()
        .filter(|s| !matches!(s.measured, Measured::NotMeasured { .. }))
        .count();
    assert_eq!(measured, 3);
    assert_eq!(r.register_update.n_syllables, 40 + 3);
}

// ---- request validation -----------------------------------------------------------------

#[test]
fn duplicate_candidate_ids_error() {
    let a = warm_analysis(&["4", "1", "3"]);
    let request = AssessRequest {
        distractors: vec![c("spell", &["4", "1", "4"])],
        ..req(&["4", "1", "3"])
    };
    assert_eq!(
        assess(&a, &cmn(), &request),
        Err(AssessError::DuplicateCandidate {
            id: CandidateId("spell".into())
        })
    );
    // Two distractors sharing an id are just as bad.
    let request = AssessRequest {
        distractors: vec![c("x", &["4", "1", "4"]), c("x", &["4", "1", "2"])],
        ..req(&["4", "1", "3"])
    };
    assert_eq!(
        assess(&a, &cmn(), &request),
        Err(AssessError::DuplicateCandidate {
            id: CandidateId("x".into())
        })
    );
}

fn matched(hit: bool) -> Vec<Evidence> {
    vec![Evidence::Transcript {
        matched_target: hit,
        confusion_hit: None,
    }]
}

#[test]
fn external_evidence_must_cover_every_syllable() {
    let a = warm_analysis(&["4", "1", "3"]);
    let pack = cmn();

    let short = AssessRequest {
        external: vec![matched(true), matched(true)],
        ..req(&["4", "1", "3"])
    };
    assert_eq!(
        assess(&a, &pack, &short),
        Err(AssessError::EvidenceLengthMismatch {
            expected: 3,
            got: 2
        })
    );

    // Empty and exactly one list per syllable are both fine, and the evidence is used.
    let with = AssessRequest {
        external: vec![matched(true), matched(true), matched(true)],
        ..req(&["4", "1", "3"])
    };
    let with = assess(&a, &pack, &with).unwrap();
    let without = assess(&a, &pack, &req(&["4", "1", "3"])).unwrap();
    assert!(with.syllables.iter().all(|s| s.basis.len() == 2));
    assert!(without.syllables.iter().all(|s| s.basis.len() == 1));
}

#[test]
fn unknown_tones_and_accents_are_errors_not_panics() {
    let a = warm_analysis(&["4", "1", "3"]);
    let pack = cmn();
    assert!(matches!(
        assess(&a, &pack, &req(&["4", "1", "9"])),
        Err(AssessError::UnknownTone { .. })
    ));
    let request = AssessRequest {
        grading: GradingTarget {
            accent: accent("cmn-Atlantis"),
            ..std_g()
        },
        ..req(&["4", "1", "3"])
    };
    assert!(matches!(
        assess(&a, &pack, &request),
        Err(AssessError::Pack { .. })
    ));
}

#[test]
fn an_assess_request_needs_only_grading_and_intended() {
    // R39: the three lists are optional on the wire.
    let json = r#"{
        "grading": {"accent": "cmn-standard", "style": null, "style_weight": 0.0},
        "intended": {"id": "spell", "targets": [
            {"tone": "4", "lexical_variants": [], "label": null}
        ]}
    }"#;
    assert_eq!(
        serde_json::from_str::<AssessRequest>(json).unwrap(),
        req(&["4"])
    );
    // The required fields stay required.
    assert!(serde_json::from_str::<AssessRequest>(
        r#"{"grading": {"accent": "cmn-standard", "style": null, "style_weight": 0.0}}"#
    )
    .is_err());
}

#[test]
fn an_assess_request_round_trips_through_json() {
    let request = AssessRequest {
        distractors: vec![c("near", &["4", "1", "4"])],
        external: vec![matched(true), matched(false), matched(true)],
        compare_accents: vec![accent("cmn-TW")],
        ..req(&["4", "1", "3"])
    };
    let json = serde_json::to_string(&request).unwrap();
    assert_eq!(
        serde_json::from_str::<AssessRequest>(&json).unwrap(),
        request
    );
}

// ---- the other two entry points ---------------------------------------------------------

#[test]
fn decode_and_lattice_are_reachable_through_the_facade() {
    let a = warm_analysis(&["2", "4", "1"]);
    let pack = cmn();
    let candidates = [intended(&["2", "4", "1"]), c("x", &["4", "4", "4"])];
    let d = decode(&a, &pack, &std_g(), &candidates).unwrap();
    assert_eq!(d.candidates[0].id, CandidateId("spell".into()));
    let l = lattice(&a, &pack, &std_g()).unwrap();
    assert_eq!(l.schema, "tonekit.lattice.v1");
    assert_eq!(l.tbus.len(), 3);
}
