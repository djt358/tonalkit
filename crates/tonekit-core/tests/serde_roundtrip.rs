use tonekit_core::*;

#[test]
fn ids_serialize_transparently() {
    assert_eq!(serde_json::to_string(&ToneId("3".into())).unwrap(), "\"3\"");
}

#[test]
fn assessment_roundtrips() {
    let a = UtteranceAssessment {
        schema: "tonekit.assessment.v1".into(),
        intended: CandidateId("c".into()),
        intended_rank: 1,
        margin_llr: 1.5,
        syllables: vec![],
        overall: None,
        accent_fit: vec![],
        register_update: Register {
            floor_st: 10.0,
            median_st: 16.0,
            ceil_st: 22.0,
            n_syllables: 3,
        },
    };
    let s = serde_json::to_string(&a).unwrap();
    assert_eq!(serde_json::from_str::<UtteranceAssessment>(&s).unwrap(), a);
}

#[test]
fn delta_is_struct_not_tuple() {
    let d = ShapeDelta {
        kind: DeltaKind::StartHigher,
        amount: 0.8,
    };
    assert!(serde_json::to_string(&d)
        .unwrap()
        .contains("\"kind\":\"StartHigher\""));
}

fn span() -> TbuSpan {
    TbuSpan {
        start_frame: 10,
        end_frame: 34,
    }
}

fn shape() -> ToneShape {
    ToneShape {
        span: span(),
        contour: (0..CONTOUR_POINTS).map(|i| 1.0 + i as f32 * 0.25).collect(),
        voiced_weights: vec![1.0; CONTOUR_POINTS],
        onset: 1.0,
        offset: 3.25,
        mean: 2.1,
        slope: 2.25,
        curvature: -0.5,
        turning_point: Some(0.4),
        range: 2.25,
        duration_ms: 240.0,
        voiced_fraction: 0.9,
        f0_confidence: 0.8,
        phonation: Some(Phonation {
            creak_ratio: 0.1,
            cpp_db: 12.0,
        }),
    }
}

fn judgement() -> ToneJudgement {
    ToneJudgement {
        expected: ToneId("3".into()),
        loglik: vec![-2.0, -1.5, -0.2, -3.0, -2.5],
        llr_target: 1.25,
        distance: Some(0.6),
        component: Some("cmn-TW/t3-low".into()),
        heard: Some(ToneId("2".into())),
        deltas: vec![ShapeDelta {
            kind: DeltaKind::TurnLater,
            amount: 40.0,
        }],
        measured: Measured::Partial {
            issues: vec![MeasureIssue::ColdStartRegister],
        },
    }
}

fn roundtrip<T>(v: &T)
where
    T: serde::Serialize + serde::de::DeserializeOwned + PartialEq + std::fmt::Debug,
{
    let s = serde_json::to_string(v).unwrap();
    assert_eq!(&serde_json::from_str::<T>(&s).unwrap(), v);
}

#[test]
fn constants_match_spec() {
    assert_eq!(SAMPLE_RATE, 16_000);
    assert_eq!(HOP, 160);
    assert_eq!(CONTOUR_POINTS, 10);
    // One hop is 10 ms at the required sample rate.
    assert_eq!(HOP as u32 * 1000 / SAMPLE_RATE, 10);
}

#[test]
fn all_id_newtypes_are_bare_strings() {
    assert_eq!(
        serde_json::to_string(&Lect("cmn".into())).unwrap(),
        "\"cmn\""
    );
    assert_eq!(
        serde_json::to_string(&AccentId("cmn-TW".into())).unwrap(),
        "\"cmn-TW\""
    );
    assert_eq!(
        serde_json::to_string(&CandidateId("c1".into())).unwrap(),
        "\"c1\""
    );
    assert_eq!(
        serde_json::from_str::<ToneId>("\"5\"").unwrap(),
        ToneId("5".into())
    );
}

#[test]
fn ids_are_hashable_map_keys() {
    let mut m = std::collections::HashMap::new();
    m.insert(ToneId("1".into()), 1);
    assert_eq!(m.get(&ToneId("1".into())), Some(&1));
}

#[test]
fn enums_use_external_tagging() {
    assert_eq!(serde_json::to_string(&Measured::Full).unwrap(), "\"Full\"");
    assert_eq!(
        serde_json::to_string(&Measured::NotMeasured {
            issue: MeasureIssue::Unvoiced
        })
        .unwrap(),
        "{\"NotMeasured\":{\"issue\":\"Unvoiced\"}}"
    );
    assert_eq!(
        serde_json::to_string(&Evidence::Neural {
            p_correct: 0.5,
            model: "m".into()
        })
        .unwrap(),
        "{\"Neural\":{\"p_correct\":0.5,\"model\":\"m\"}}"
    );
    assert_eq!(
        serde_json::to_string(&RegisterSource::ColdStart).unwrap(),
        "\"ColdStart\""
    );
}

fn assert_copy_eq<T: Copy + Eq>() {}

#[test]
fn fieldless_enums_are_copy_and_eq() {
    assert_copy_eq::<DeltaKind>();
    assert_copy_eq::<MeasureIssue>();
    assert_copy_eq::<EvidenceKind>();
    assert_copy_eq::<RegisterSource>();
}

#[test]
fn nested_types_roundtrip() {
    let lattice = ToneLattice {
        schema: "tonekit.lattice.v1".into(),
        lect: Lect("cmn".into()),
        accent: AccentId("cmn-standard".into()),
        inventory: ["1", "2", "3", "4", "5"]
            .iter()
            .map(|t| ToneId((*t).into()))
            .collect(),
        prior: vec![0.2; 5],
        tbus: vec![LatticeTbu {
            span: span(),
            loglik: vec![-1.0; 5],
            posterior: vec![0.2; 5],
            measured: Measured::Full,
            shape: Some(shape()),
        }],
    };
    roundtrip(&lattice);

    let fit = SyllableFit {
        span: span(),
        judgement: judgement(),
    };
    let decode = DecodeResult {
        candidates: vec![CandidateScore {
            id: CandidateId("c".into()),
            llr: 3.0,
            posterior: 0.9,
            syllables: vec![fit],
        }],
        null_llr: -1.0,
        null_posterior: 0.1,
    };
    roundtrip(&decode);

    roundtrip(&Evidence::Acoustic {
        judgement: judgement(),
    });
    roundtrip(&Evidence::Transcript {
        matched_target: false,
        confusion_hit: Some(ConfusionHit {
            tone: ToneId("2".into()),
            text: "shí".into(),
        }),
    });

    let target = GradingTarget {
        accent: AccentId("cmn-TW".into()),
        style: Some(StyleProfile {
            accent: AccentId("cmn-TW".into()),
            tones: vec![StyleTone {
                tone: ToneId("1".into()),
                contour: vec![4.5; CONTOUR_POINTS],
                n: 12,
            }],
            mean_range: 1.8,
        }),
        style_weight: 0.3,
    };
    roundtrip(&target);
    roundtrip(&Candidate {
        id: CandidateId("c".into()),
        targets: vec![ToneTarget {
            tone: ToneId("1".into()),
            lexical_variants: vec![WeightedTone {
                tone: ToneId("2".into()),
                weight: 0.3,
            }],
            label: Some("星期".into()),
        }],
    });
}

#[test]
fn analysis_roundtrips() {
    let a = Analysis {
        f0: F0Track {
            frames: vec![
                F0Frame {
                    hz: Some(220.0),
                    voiced_p: 0.95,
                },
                F0Frame {
                    hz: None,
                    voiced_p: 0.0,
                },
            ],
            provider: "pyin".into(),
        },
        energy: EnergyTrack {
            db: vec![-30.0, -60.0],
        },
        nuclei: vec![Nucleus {
            frame: 0,
            strength_db: 6.0,
        }],
        boundaries: vec![0, 1],
        speech: Some(FrameRange { start: 0, end: 1 }),
        register: Register {
            floor_st: 10.0,
            median_st: 16.0,
            ceil_st: 22.0,
            n_syllables: 0,
        },
        register_source: RegisterSource::ColdStart,
        voiced_st: vec![16.0],
        issues: vec![MeasureIssue::LowSnr],
        sonority: vec![0.5, 0.9],
    };
    roundtrip(&a);
}

#[test]
fn syllable_assessment_roundtrips() {
    roundtrip(&SyllableAssessment {
        expected: ToneId("4".into()),
        p_correct: 0.7,
        distance: None,
        heard: None,
        heard_as: Some("shí".into()),
        deltas: vec![],
        component: None,
        measured: Measured::NotMeasured {
            issue: MeasureIssue::TooShort,
        },
        basis: vec![EvidenceKind::Acoustic, EvidenceKind::Transcript],
    });
    roundtrip(&FusionWeights {
        beta0: 0.0,
        beta_acoustic: 1.0,
        beta_transcript: 0.5,
        beta_neural: 0.0,
        veto_cap: 0.05,
    });
    roundtrip(&AccentFit {
        accent: AccentId("cmn-standard".into()),
        llr: 2.0,
    });
}

#[test]
fn assess_error_messages_and_roundtrip() {
    assert_eq!(AssessError::EmptyAudio.to_string(), "audio is empty");
    assert_eq!(
        AssessError::UnsupportedSampleRate { got: 44_100 }.to_string(),
        format!("unsupported sample rate 44100 Hz (expected {SAMPLE_RATE} Hz)")
    );
    assert_eq!(
        AssessError::EvidenceLengthMismatch {
            expected: 3,
            got: 2
        }
        .to_string(),
        "evidence length mismatch: expected 3 syllables, got 2"
    );
    assert_eq!(
        AssessError::Pack {
            message: "bad".into()
        }
        .to_string(),
        "pack error: bad"
    );
    assert_eq!(
        AssessError::TooLong {
            seconds: 30.01,
            max: 30.0
        }
        .to_string(),
        "audio is 30.01 s long; at most 30 s can be assessed"
    );
    assert_eq!(
        AssessError::InvalidRequest {
            message: "empty candidate set".into()
        }
        .to_string(),
        "invalid request: empty candidate set"
    );
    for e in [
        AssessError::EmptyAudio,
        AssessError::UnknownTone {
            tone: ToneId("9".into()),
        },
        AssessError::DuplicateCandidate {
            id: CandidateId("c".into()),
        },
        AssessError::TooLong {
            seconds: 31.5,
            max: 30.0,
        },
        AssessError::InvalidRequest {
            message: "intended candidate missing".into(),
        },
    ] {
        roundtrip(&e);
        let _: &dyn std::error::Error = &e;
    }
}

#[test]
fn measure_issues_serialise_by_name() {
    for (issue, name) in [
        (MeasureIssue::InvalidRegister, "\"InvalidRegister\""),
        (MeasureIssue::InvalidEvidence, "\"InvalidEvidence\""),
    ] {
        assert_eq!(serde_json::to_string(&issue).unwrap(), name);
        roundtrip(&issue);
    }
}
