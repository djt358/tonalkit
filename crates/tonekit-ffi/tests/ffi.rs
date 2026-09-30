//! The exported FFI functions, called directly from Rust on the host: what Swift calls through
//! the generated bindings, minus the bindings themselves (Task 12).
//!
//! The 4-1-3 recording is the shared fixture `fixtures/spoken-413.wav` with its expected
//! `spoken-413.assessment.json` (`tonekit assess --json`); the Swift tests on the iOS Simulator
//! must reproduce the same numbers. Comparisons are tolerance-based (ruling R41).

use std::path::Path;

use serde_json::Value;
use tonekit::{
    AccentId, AssessError, AssessRequest, Candidate, CandidateId, F0Frame, F0Track, GradingTarget,
    Lect, MeasureIssue, Measured, Register, RegisterSource, ToneId, ToneTarget,
    UtteranceAssessment,
};
use tonekit_ffi::{analyze, assess, decode, lattice, Pack};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");
const FIXTURES: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../../fixtures");

/// Absolute tolerance on each number of an assessment against the checked-in JSON (R41).
const TOLERANCE: f64 = 1e-4;
const RATE: u32 = 16_000;

fn pack() -> std::sync::Arc<Pack> {
    Pack::from_toml(CMN_TOML.to_owned(), Some(CMN_CALIB.to_owned())).unwrap()
}

/// The checked-in fixture WAV as floats in -1..1 (WAVE_FORMAT_EXTENSIBLE float32, 16 kHz mono).
fn fixture_pcm() -> Vec<f32> {
    let path = Path::new(FIXTURES).join("spoken-413.wav");
    let mut reader = hound::WavReader::open(&path)
        .unwrap_or_else(|e| panic!("{} is unreadable ({e})", path.display()));
    let spec = reader.spec();
    assert_eq!((spec.channels, spec.sample_rate), (1, RATE));
    reader.samples::<f32>().collect::<Result<_, _>>().unwrap()
}

fn fixture_json() -> Value {
    let path = Path::new(FIXTURES).join("spoken-413.assessment.json");
    serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap()
}

fn candidate(id: &str, tones: &[&str], labels: &[&str]) -> Candidate {
    Candidate {
        id: CandidateId(id.into()),
        targets: tones
            .iter()
            .enumerate()
            .map(|(i, tone)| ToneTarget {
                tone: ToneId((*tone).into()),
                lexical_variants: Vec::new(),
                label: labels.get(i).map(|l| (*l).to_owned()),
            })
            .collect(),
    }
}

fn standard() -> GradingTarget {
    GradingTarget {
        accent: AccentId("cmn-standard".into()),
        style: None,
        style_weight: 0.0,
    }
}

/// Exactly what `tonekit assess --tones "4 1 3" --labels "yi bei shui" --json` grades.
fn request_413() -> AssessRequest {
    AssessRequest {
        grading: standard(),
        intended: candidate("intended", &["4", "1", "3"], &["yi", "bei", "shui"]),
        distractors: Vec::new(),
        external: Vec::new(),
        compare_accents: Vec::new(),
    }
}

/// The largest numeric `|want - got|` anywhere in two JSON values, or a description of the first
/// place they differ: a number off by more than `tol`, or any string, bool, null, array length,
/// object key or type that is not identical.
fn json_max_diff(want: &Value, got: &Value, tol: f64) -> Result<f64, String> {
    fn walk(path: &str, want: &Value, got: &Value, tol: f64, max: &mut f64) -> Result<(), String> {
        match (want, got) {
            (Value::Number(w), Value::Number(g)) => {
                let (w, g) = (w.as_f64().unwrap(), g.as_f64().unwrap());
                let diff = (w - g).abs();
                if diff.is_nan() || diff > tol {
                    return Err(format!("{path}: {w} vs {g} (|diff| {diff:e} > {tol:e})"));
                }
                *max = max.max(diff);
                Ok(())
            }
            (Value::Array(w), Value::Array(g)) => {
                if w.len() != g.len() {
                    return Err(format!("{path}: {} elements vs {}", w.len(), g.len()));
                }
                for (i, (w, g)) in w.iter().zip(g).enumerate() {
                    walk(&format!("{path}[{i}]"), w, g, tol, max)?;
                }
                Ok(())
            }
            (Value::Object(w), Value::Object(g)) => {
                if let Some(key) = w.keys().find(|k| !g.contains_key(*k)) {
                    return Err(format!(
                        "{path}: key {key:?} is missing from the other side"
                    ));
                }
                if let Some(key) = g.keys().find(|k| !w.contains_key(*k)) {
                    return Err(format!("{path}: unexpected key {key:?}"));
                }
                for (key, w) in w {
                    walk(&format!("{path}.{key}"), w, &g[key], tol, max)?;
                }
                Ok(())
            }
            (w, g) if w == g => Ok(()),
            (w, g) => Err(format!("{path}: {w} vs {g}")),
        }
    }
    let mut max = 0.0_f64;
    walk("$", want, got, tol, &mut max)?;
    Ok(max)
}

// ---- the fixture pair ---------------------------------------------------------------------

#[test]
fn the_spoken_fixture_reproduces_the_cli_assessment() {
    let analysis = analyze(fixture_pcm(), RATE, None, None).unwrap();
    let assessment = assess(analysis, pack(), request_413()).unwrap();

    let want = fixture_json();
    let got = serde_json::to_value(&assessment).unwrap();
    let max = json_max_diff(&want, &got, TOLERANCE)
        .unwrap_or_else(|e| panic!("differs from fixtures/spoken-413.assessment.json: {e}"));
    println!("fixture drift: json max |diff| = {max:e}");

    // The three things the Swift test asserts, spelled out.
    assert_eq!(assessment.intended_rank, 1);
    assert!(
        (f64::from(assessment.overall.unwrap()) - want["overall"].as_f64().unwrap()).abs()
            < TOLERANCE
    );
    let want_syllables = want["syllables"].as_array().unwrap();
    assert_eq!(assessment.syllables.len(), want_syllables.len());
    for (got, want) in assessment.syllables.iter().zip(want_syllables) {
        let want_p = want["p_correct"].as_f64().unwrap();
        assert!((f64::from(got.p_correct) - want_p).abs() < TOLERANCE);
    }
}

#[test]
fn decode_and_lattice_are_exported_too() {
    let analysis = analyze(fixture_pcm(), RATE, None, None).unwrap();
    let pack = pack();

    let decoded = decode(
        analysis.clone(),
        pack.clone(),
        standard(),
        vec![
            candidate("right", &["4", "1", "3"], &[]),
            candidate("wrong", &["1", "4", "2"], &[]),
        ],
    )
    .unwrap();
    assert_eq!(decoded.candidates.len(), 2);
    assert_eq!(decoded.candidates[0].id, CandidateId("right".into()));
    assert!(decoded.candidates[0].llr > decoded.candidates[1].llr);

    let lat = lattice(analysis, pack, standard()).unwrap();
    assert_eq!(lat.schema, "tonekit.lattice.v1");
    assert_eq!(lat.lect, Lect("cmn".into()));
    assert_eq!(lat.inventory.len(), 5);
    assert_eq!(lat.tbus.len(), 3);
}

// ---- Pack ---------------------------------------------------------------------------------

#[test]
fn a_pack_reports_its_lect_base_accent_and_inventory() {
    let pack = pack();
    assert_eq!(pack.lect(), Lect("cmn".into()));
    assert_eq!(pack.base_accent(), AccentId("cmn-standard".into()));
    let tones: Vec<String> = pack.inventory().into_iter().map(|t| t.0).collect();
    assert_eq!(tones, ["1", "2", "3", "4", "5"]);
}

#[test]
fn the_calibration_is_optional() {
    let pack = Pack::from_toml(CMN_TOML.to_owned(), None).unwrap();
    assert_eq!(pack.lect(), Lect("cmn".into()));
}

#[test]
fn a_bad_pack_is_a_pack_error_with_the_reason() {
    let malformed = Pack::from_toml("this is [not toml".to_owned(), None).map(|_| ());
    assert!(
        matches!(&malformed, Err(AssessError::Pack { message }) if message.contains("pack parse error")),
        "{malformed:?}"
    );

    let bad_calibration =
        Pack::from_toml(CMN_TOML.to_owned(), Some("{ not json".to_owned())).map(|_| ());
    assert!(
        matches!(&bad_calibration, Err(AssessError::Pack { message }) if !message.is_empty()),
        "{bad_calibration:?}"
    );

    // Well-formed TOML that is not a pack.
    let invalid = Pack::from_toml("[pack]\nlect = \"cmn\"\n".to_owned(), None).map(|_| ());
    assert!(
        matches!(invalid, Err(AssessError::Pack { .. })),
        "{invalid:?}"
    );
}

// ---- errors cross the boundary as values --------------------------------------------------

#[test]
fn analyze_rejects_what_the_facade_rejects() {
    assert_eq!(
        analyze(Vec::new(), RATE, None, None).unwrap_err(),
        AssessError::EmptyAudio
    );
    assert_eq!(
        analyze(vec![0.0; 4_800], 44_100, None, None).unwrap_err(),
        AssessError::UnsupportedSampleRate { got: 44_100 }
    );
    assert_eq!(
        analyze(vec![0.0; 30 * RATE as usize + 160], RATE, None, None).unwrap_err(),
        AssessError::TooLong {
            seconds: 30.01,
            max: 30.0
        }
    );
}

#[test]
fn an_unusable_register_is_replaced_not_an_error() {
    // I1: a corrupted persisted register must not stop grading.
    let inverted = Register {
        floor_st: 20.0,
        median_st: 15.0,
        ceil_st: 10.0,
        n_syllables: 40,
    };
    let analysis = analyze(fixture_pcm(), RATE, Some(inverted), None).unwrap();
    assert_eq!(analysis.register_source, RegisterSource::ColdStart);
    assert!(analysis.issues.contains(&MeasureIssue::InvalidRegister));
    let cold = analyze(fixture_pcm(), RATE, None, None).unwrap();
    assert_eq!(analysis.register, cold.register);
}

#[test]
fn assess_errors_are_errors_not_panics() {
    let analysis = analyze(fixture_pcm(), RATE, None, None).unwrap();
    let pack = pack();

    let unknown_tone = AssessRequest {
        intended: candidate("intended", &["4", "9", "3"], &[]),
        ..request_413()
    };
    assert_eq!(
        assess(analysis.clone(), pack.clone(), unknown_tone).unwrap_err(),
        AssessError::UnknownTone {
            tone: ToneId("9".into())
        }
    );

    let unknown_accent = AssessRequest {
        grading: GradingTarget {
            accent: AccentId("cmn-XX".into()),
            ..standard()
        },
        ..request_413()
    };
    assert!(matches!(
        assess(analysis.clone(), pack.clone(), unknown_accent),
        Err(AssessError::Pack { message }) if message.contains("cmn-XX")
    ));

    let duplicate = AssessRequest {
        distractors: vec![candidate("intended", &["1", "1", "1"], &[])],
        ..request_413()
    };
    assert!(matches!(
        assess(analysis.clone(), pack.clone(), duplicate),
        Err(AssessError::DuplicateCandidate { .. })
    ));

    // M4: request errors are not pack errors.
    let no_targets = AssessRequest {
        intended: candidate("intended", &[], &[]),
        ..request_413()
    };
    assert_eq!(
        assess(analysis.clone(), pack.clone(), no_targets).unwrap_err(),
        AssessError::InvalidRequest {
            message: "candidate intended has no targets".into()
        }
    );
    assert_eq!(
        decode(analysis, pack, standard(), Vec::new()).unwrap_err(),
        AssessError::InvalidRequest {
            message: "empty candidate set".into()
        }
    );
}

// ---- a given register and an external f0 track --------------------------------------------

#[test]
fn a_given_register_is_used_and_updated() {
    let cold = analyze(fixture_pcm(), RATE, None, None).unwrap();
    let register = assess(cold, pack(), request_413()).unwrap().register_update;
    assert!(register.n_syllables > 0);

    let warm = analyze(fixture_pcm(), RATE, Some(register.clone()), None).unwrap();
    assert_eq!(warm.register, register);
    let again = assess(warm, pack(), request_413()).unwrap();
    assert_eq!(again.register_update.n_syllables, register.n_syllables + 3);
}

#[test]
fn an_external_f0_track_is_used() {
    let pyin = analyze(fixture_pcm(), RATE, None, None).unwrap();
    assert_eq!(pyin.f0.provider, "pyin");

    // Feed pYIN's own track back in as if a neural pitch model had produced it.
    let track = F0Track {
        frames: pyin.f0.frames.clone(),
        provider: "somebody-else".into(),
    };
    let external = analyze(fixture_pcm(), RATE, None, Some(track)).unwrap();
    assert_eq!(external.f0.provider, "external");
    assert_eq!(external.f0.frames.len(), pyin.f0.frames.len());

    let from_pyin = assess(pyin, pack(), request_413()).unwrap();
    let from_external = assess(external, pack(), request_413()).unwrap();
    assert_eq!(
        from_external.syllables.len(),
        from_pyin.syllables.len(),
        "same syllables"
    );
    assert!(
        (from_external.overall.unwrap() - from_pyin.overall.unwrap()).abs() < 0.05,
        "{:?} vs {:?}",
        from_external.overall,
        from_pyin.overall
    );
}

/// Ruling R43 at the FFI boundary: Swift can hand over any bit pattern as an f0 track.
#[test]
fn a_hostile_external_track_cannot_poison_the_assessment() {
    let pyin = analyze(fixture_pcm(), RATE, None, None).unwrap();
    let mut frames = pyin.f0.frames;
    let voiced: Vec<usize> = frames
        .iter()
        .enumerate()
        .filter_map(|(i, f)| f.hz.map(|_| i))
        .collect();
    assert!(
        voiced.len() > 40,
        "the fixture should have plenty of voiced frames"
    );
    frames[voiced[5]].hz = Some(f32::NAN);
    frames[voiced[10]].hz = Some(-5.0);
    frames[voiced[15]].hz = Some(f32::INFINITY);
    frames[voiced[20]].voiced_p = f32::NAN;
    frames[voiced[25]].voiced_p = 42.0;
    let hostile = F0Track {
        frames,
        provider: "hostile".into(),
    };

    let analysis = analyze(fixture_pcm(), RATE, None, Some(hostile)).unwrap();
    assert!(analysis.f0.frames.iter().all(|f: &F0Frame| {
        f.hz.is_none_or(|hz| hz.is_finite() && hz > 0.0) && (0.0..=1.0).contains(&f.voiced_p)
    }));
    let r: UtteranceAssessment = assess(analysis, pack(), request_413()).unwrap();
    assert!(r.overall.is_some_and(f32::is_finite));
    assert!(r.margin_llr.is_finite());
    assert!(r
        .syllables
        .iter()
        .all(|s| s.p_correct.is_finite() && s.distance.is_none_or(f32::is_finite)));
    assert!(r.syllables.iter().all(|s| matches!(
        &s.measured,
        Measured::Partial { issues } if issues.contains(&MeasureIssue::ColdStartRegister)
    )));
}
