use approx::assert_abs_diff_eq;
use tonekit_core::{
    AccentFit, AccentId, AssessError, CandidateId, CandidateScore, ConfusionHit, DecodeResult,
    DeltaKind, Evidence, EvidenceKind, FusionWeights, MeasureIssue, Measured, Register, ShapeDelta,
    SyllableFit, TbuSpan, ToneId, ToneJudgement,
};
use tonekit_fuse::{assemble, fuse_syllable};

// ---------------------------------------------------------------------------------------------
// Helpers.
// ---------------------------------------------------------------------------------------------

/// A judgement with the given `llr_target` and `measured`; expected tone "4", everything else empty.
fn fit(llr: f32, measured: Measured) -> SyllableFit {
    SyllableFit {
        span: TbuSpan {
            start_frame: 0,
            end_frame: 10,
        },
        judgement: ToneJudgement {
            expected: ToneId("4".into()),
            loglik: vec![],
            llr_target: llr,
            distance: None,
            component: None,
            heard: None,
            deltas: vec![],
            measured,
        },
    }
}

fn seed() -> FusionWeights {
    FusionWeights {
        beta0: 0.0,
        beta_acoustic: 1.0,
        beta_transcript: 0.5,
        beta_neural: 0.0,
        veto_cap: 0.05,
    }
}

fn unmeasured() -> Measured {
    Measured::NotMeasured {
        issue: MeasureIssue::Unvoiced,
    }
}

fn sigmoid(z: f32) -> f32 {
    1.0 / (1.0 + (-z).exp())
}

fn logit(p: f32) -> f32 {
    (p / (1.0 - p)).ln()
}

fn transcript(matched_target: bool) -> Evidence {
    Evidence::Transcript {
        matched_target,
        confusion_hit: None,
    }
}

fn confusion(tone: &str, text: &str) -> Evidence {
    Evidence::Transcript {
        matched_target: false,
        confusion_hit: Some(ConfusionHit {
            tone: ToneId(tone.into()),
            text: text.into(),
        }),
    }
}

fn neural(p_correct: f32) -> Evidence {
    Evidence::Neural {
        p_correct,
        model: "test-nn".into(),
    }
}

fn id(s: &str) -> CandidateId {
    CandidateId(s.into())
}

fn cand(name: &str, llr: f32, syllables: Vec<SyllableFit>) -> CandidateScore {
    CandidateScore {
        id: id(name),
        llr,
        posterior: 0.0,
        syllables,
    }
}

fn decoded(candidates: Vec<CandidateScore>, null_llr: f32) -> DecodeResult {
    DecodeResult {
        candidates,
        null_llr,
        null_posterior: 0.0,
    }
}

fn register() -> Register {
    Register {
        floor_st: 10.0,
        median_st: 14.0,
        ceil_st: 18.0,
        n_syllables: 7,
    }
}

fn run(
    r: &DecodeResult,
    intended: &str,
    external: &[Vec<Evidence>],
) -> Result<tonekit_core::UtteranceAssessment, AssessError> {
    assemble(r, &id(intended), external, &seed(), vec![], register())
}

// ---------------------------------------------------------------------------------------------
// The brief's six tests.
// ---------------------------------------------------------------------------------------------

#[test]
fn acoustic_only_is_sigmoid_of_llr() {
    let a = fuse_syllable(&fit(2.0, Measured::Full), &[], &seed());
    approx::assert_abs_diff_eq!(a.p_correct, 1.0 / (1.0 + (-2.0f32).exp()), epsilon = 1e-5);
    assert_eq!(a.basis, vec![EvidenceKind::Acoustic]);
}

#[test]
fn confusion_hit_vetoes() {
    let a = fuse_syllable(
        &fit(4.0, Measured::Full),
        &[Evidence::Transcript {
            matched_target: false,
            confusion_hit: Some(ConfusionHit {
                tone: ToneId("4".into()),
                text: "睡".into(),
            }),
        }],
        &seed(),
    );
    assert!(a.p_correct <= 0.05);
    assert_eq!(a.heard_as.as_deref(), Some("睡"));
}

#[test]
fn unmeasured_acoustic_drops_term() {
    let a = fuse_syllable(
        &fit(
            -3.0,
            Measured::NotMeasured {
                issue: MeasureIssue::Unvoiced,
            },
        ),
        &[],
        &seed(),
    );
    approx::assert_abs_diff_eq!(a.p_correct, 0.5, epsilon = 1e-6);
    assert!(a.basis.is_empty());
}

#[test]
fn overall_is_min_over_measured_and_none_when_nothing_measured() {
    // Two measured syllables with p = .9 and p = .2 (llr = logit p, beta_acoustic = 1).
    let r = decoded(
        vec![cand(
            "a",
            5.0,
            vec![
                fit(logit(0.9), Measured::Full),
                fit(logit(0.2), Measured::Full),
            ],
        )],
        0.0,
    );
    let out = run(&r, "a", &[]).unwrap();
    assert_abs_diff_eq!(out.syllables[0].p_correct, 0.9, epsilon = 1e-5);
    assert_abs_diff_eq!(out.syllables[1].p_correct, 0.2, epsilon = 1e-5);
    assert_abs_diff_eq!(out.overall.unwrap(), 0.2, epsilon = 1e-5);

    // Nothing measured: overall is None ("tone not checked").
    let r = decoded(
        vec![cand(
            "a",
            5.0,
            vec![fit(1.0, unmeasured()), fit(-2.0, unmeasured())],
        )],
        0.0,
    );
    let out = run(&r, "a", &[]).unwrap();
    assert_eq!(out.syllables.len(), 2);
    assert_eq!(out.overall, None);
}

#[test]
fn rank_and_margin() {
    // The intended candidate is second of two: llr 1.0 against 3.0, with null_llr 0.5.
    let r = decoded(
        vec![
            cand("other", 3.0, vec![fit(0.0, Measured::Full)]),
            cand("mine", 1.0, vec![fit(0.0, Measured::Full)]),
        ],
        0.5,
    );
    let out = run(&r, "mine", &[]).unwrap();
    assert_eq!(out.intended_rank, 2);
    assert_abs_diff_eq!(out.margin_llr, -2.0, epsilon = 1e-6);
    assert_eq!(out.intended, id("mine"));
}

#[test]
fn evidence_length_mismatch_errors() {
    // Three syllables but evidence for only two.
    let r = decoded(
        vec![cand(
            "a",
            1.0,
            vec![
                fit(0.0, Measured::Full),
                fit(0.0, Measured::Full),
                fit(0.0, Measured::Full),
            ],
        )],
        0.0,
    );
    let external = vec![vec![], vec![]];
    assert_eq!(
        run(&r, "a", &external),
        Err(AssessError::EvidenceLengthMismatch {
            expected: 3,
            got: 2
        })
    );
}

// ---------------------------------------------------------------------------------------------
// fuse_syllable: the fusion formula (spec §7.4).
// ---------------------------------------------------------------------------------------------

#[test]
fn no_evidence_is_sigmoid_of_beta0_with_empty_basis() {
    let w = FusionWeights {
        beta0: 1.0,
        ..seed()
    };
    let a = fuse_syllable(&fit(9.0, unmeasured()), &[], &w);
    assert_abs_diff_eq!(a.p_correct, sigmoid(1.0), epsilon = 1e-6);
    assert!(a.basis.is_empty());
}

#[test]
fn beta0_shifts_the_logit() {
    let w = FusionWeights {
        beta0: -1.5,
        ..seed()
    };
    let a = fuse_syllable(&fit(2.0, Measured::Full), &[], &w);
    assert_abs_diff_eq!(a.p_correct, sigmoid(0.5), epsilon = 1e-6);
}

#[test]
fn transcript_match_adds_beta_transcript() {
    let hit = fuse_syllable(&fit(1.0, Measured::Full), &[transcript(true)], &seed());
    assert_abs_diff_eq!(hit.p_correct, sigmoid(1.0 + 0.5), epsilon = 1e-6);
    assert_eq!(
        hit.basis,
        vec![EvidenceKind::Acoustic, EvidenceKind::Transcript]
    );

    // A transcript that did not match contributes x_tr = 0: no change, but it is still basis.
    let miss = fuse_syllable(&fit(1.0, Measured::Full), &[transcript(false)], &seed());
    assert_abs_diff_eq!(miss.p_correct, sigmoid(1.0), epsilon = 1e-6);
    assert_eq!(
        miss.basis,
        vec![EvidenceKind::Acoustic, EvidenceKind::Transcript]
    );
}

#[test]
fn transcript_alone_with_unmeasured_acoustic() {
    let a = fuse_syllable(&fit(-3.0, unmeasured()), &[transcript(true)], &seed());
    assert_abs_diff_eq!(a.p_correct, sigmoid(0.5), epsilon = 1e-6);
    assert_eq!(a.basis, vec![EvidenceKind::Transcript]);
}

#[test]
fn neural_term_uses_logit_of_p() {
    let w = FusionWeights {
        beta_neural: 1.0,
        ..seed()
    };
    let a = fuse_syllable(&fit(0.0, Measured::Full), &[neural(0.8)], &w);
    assert_abs_diff_eq!(a.p_correct, 0.8, epsilon = 1e-5);
    assert_eq!(a.basis, vec![EvidenceKind::Acoustic, EvidenceKind::Neural]);

    // Weighted: 0.5·logit(0.8) on top of an acoustic llr of 1.0.
    let w = FusionWeights {
        beta_neural: 0.5,
        ..seed()
    };
    let a = fuse_syllable(&fit(1.0, Measured::Full), &[neural(0.8)], &w);
    assert_abs_diff_eq!(a.p_correct, sigmoid(1.0 + 0.5 * logit(0.8)), epsilon = 1e-5);
}

#[test]
fn neural_with_zero_weight_changes_nothing_but_is_basis() {
    let a = fuse_syllable(&fit(1.0, Measured::Full), &[neural(0.1)], &seed());
    assert_abs_diff_eq!(a.p_correct, sigmoid(1.0), epsilon = 1e-6);
    assert_eq!(a.basis, vec![EvidenceKind::Acoustic, EvidenceKind::Neural]);
}

#[test]
fn neural_probability_is_clamped_away_from_zero_and_one() {
    let w = FusionWeights {
        beta_neural: 1.0,
        ..seed()
    };
    // p = 1 is treated as 1 − 1e-6 and p = 0 as 1e-6, so neither saturates to exactly 0 or 1.
    let hi = fuse_syllable(&fit(0.0, unmeasured()), &[neural(1.0)], &w);
    assert!(hi.p_correct < 1.0);
    assert_abs_diff_eq!(hi.p_correct, 1.0 - 1e-6, epsilon = 1e-6);
    let lo = fuse_syllable(&fit(0.0, unmeasured()), &[neural(0.0)], &w);
    assert!(lo.p_correct > 0.0);
    assert_abs_diff_eq!(lo.p_correct, 1e-6, epsilon = 5e-7);
    // A finite acoustic term still combines with the clamped logit instead of being erased by -inf.
    let mixed = fuse_syllable(&fit(5.0, Measured::Full), &[neural(0.0)], &w);
    assert!(mixed.p_correct > 0.0 && mixed.p_correct.is_finite());
    // Values outside [0, 1] are clamped the same way rather than producing NaN.
    let wild = fuse_syllable(&fit(0.0, unmeasured()), &[neural(7.0)], &w);
    assert_abs_diff_eq!(wild.p_correct, hi.p_correct, epsilon = 1e-6);
    let neg = fuse_syllable(&fit(0.0, unmeasured()), &[neural(-3.0)], &w);
    assert_abs_diff_eq!(neg.p_correct, lo.p_correct, epsilon = 1e-6);
}

#[test]
fn basis_is_ordered_and_has_no_duplicates() {
    let w = FusionWeights {
        beta_neural: 1.0,
        ..seed()
    };
    // External evidence arrives in the "wrong" order and with a repeated transcript.
    let external = [neural(0.5), transcript(true), transcript(true)];
    let a = fuse_syllable(&fit(0.0, Measured::Full), &external, &w);
    assert_eq!(
        a.basis,
        vec![
            EvidenceKind::Acoustic,
            EvidenceKind::Transcript,
            EvidenceKind::Neural
        ]
    );
    // Each Transcript entry still contributes its term: 0.5 + 0.5, and logit(0.5) = 0.
    assert_abs_diff_eq!(a.p_correct, sigmoid(1.0), epsilon = 1e-6);
}

#[test]
fn external_acoustic_evidence_is_ignored() {
    let stray = Evidence::Acoustic {
        judgement: fit(5.0, Measured::Full).judgement,
    };
    // Acoustic comes from the fit only: an unmeasured fit stays unmeasured ...
    let a = fuse_syllable(
        &fit(-3.0, unmeasured()),
        std::slice::from_ref(&stray),
        &seed(),
    );
    assert_abs_diff_eq!(a.p_correct, 0.5, epsilon = 1e-6);
    assert!(a.basis.is_empty());
    // ... and a measured fit is not double counted.
    let b = fuse_syllable(
        &fit(1.0, Measured::Full),
        std::slice::from_ref(&stray),
        &seed(),
    );
    assert_abs_diff_eq!(b.p_correct, sigmoid(1.0), epsilon = 1e-6);
    assert_eq!(b.basis, vec![EvidenceKind::Acoustic]);
}

#[test]
fn partial_measurement_counts_as_measured() {
    let m = Measured::Partial {
        issues: vec![MeasureIssue::LowSnr],
    };
    let a = fuse_syllable(&fit(2.0, m.clone()), &[], &seed());
    assert_abs_diff_eq!(a.p_correct, sigmoid(2.0), epsilon = 1e-6);
    assert_eq!(a.basis, vec![EvidenceKind::Acoustic]);
    assert_eq!(a.measured, m);
}

// ---------------------------------------------------------------------------------------------
// fuse_syllable: confusion-set veto and `heard`.
// ---------------------------------------------------------------------------------------------

#[test]
fn veto_is_a_cap_and_never_raises_p() {
    // Already below the cap: unchanged.
    let low = fuse_syllable(&fit(-6.0, Measured::Full), &[confusion("2", "谁")], &seed());
    assert_abs_diff_eq!(low.p_correct, sigmoid(-6.0), epsilon = 1e-6);
    assert!(low.p_correct < 0.05);

    // Above the cap: pulled down to exactly the cap.
    let high = fuse_syllable(&fit(4.0, Measured::Full), &[confusion("2", "谁")], &seed());
    assert_abs_diff_eq!(high.p_correct, 0.05, epsilon = 1e-7);

    // The cap comes from the weights.
    let w = FusionWeights {
        veto_cap: 0.2,
        ..seed()
    };
    let custom = fuse_syllable(&fit(4.0, Measured::Full), &[confusion("2", "谁")], &w);
    assert_abs_diff_eq!(custom.p_correct, 0.2, epsilon = 1e-7);
}

#[test]
fn veto_applies_with_unmeasured_acoustic() {
    let w = FusionWeights {
        beta0: 3.0,
        ..seed()
    };
    let a = fuse_syllable(&fit(0.0, unmeasured()), &[confusion("1", "水")], &w);
    assert_abs_diff_eq!(a.p_correct, 0.05, epsilon = 1e-7);
    assert_eq!(a.basis, vec![EvidenceKind::Transcript]);
    assert_eq!(a.heard_as.as_deref(), Some("水"));
}

#[test]
fn confusion_hit_supplies_heard_only_when_acoustic_has_none() {
    // Acoustic heard is None: fall back to the confusion tone.
    let a = fuse_syllable(&fit(1.0, Measured::Full), &[confusion("3", "水")], &seed());
    assert_eq!(a.heard, Some(ToneId("3".into())));
    assert_eq!(a.heard_as.as_deref(), Some("水"));

    // Acoustic heard is Some: it wins, `heard_as` still comes from the hit.
    let mut f = fit(1.0, Measured::Full);
    f.judgement.heard = Some(ToneId("2".into()));
    let b = fuse_syllable(&f, &[confusion("3", "水")], &seed());
    assert_eq!(b.heard, Some(ToneId("2".into())));
    assert_eq!(b.heard_as.as_deref(), Some("水"));
}

#[test]
fn no_confusion_hit_leaves_heard_alone() {
    let a = fuse_syllable(&fit(1.0, Measured::Full), &[transcript(true)], &seed());
    assert_eq!(a.heard, None);
    assert_eq!(a.heard_as, None);

    let mut f = fit(1.0, Measured::Full);
    f.judgement.heard = Some(ToneId("2".into()));
    let b = fuse_syllable(&f, &[], &seed());
    assert_eq!(b.heard, Some(ToneId("2".into())));
    assert_eq!(b.heard_as, None);
}

#[test]
fn veto_is_found_among_several_evidence_entries() {
    let w = FusionWeights {
        beta_neural: 1.0,
        ..seed()
    };
    let external = [transcript(true), neural(0.99), confusion("1", "书")];
    let a = fuse_syllable(&fit(6.0, Measured::Full), &external, &w);
    assert!(a.p_correct <= 0.05);
    assert_eq!(a.heard_as.as_deref(), Some("书"));
    assert_eq!(
        a.basis,
        vec![
            EvidenceKind::Acoustic,
            EvidenceKind::Transcript,
            EvidenceKind::Neural
        ]
    );
}

#[test]
fn judgement_fields_are_copied() {
    let mut f = fit(0.5, Measured::Full);
    f.judgement.distance = Some(1.25);
    f.judgement.component = Some("cmn-TW/t3-low".into());
    f.judgement.deltas = vec![
        ShapeDelta {
            kind: DeltaKind::StartHigher,
            amount: 0.75,
        },
        ShapeDelta {
            kind: DeltaKind::TurnLater,
            amount: 40.0,
        },
    ];
    f.judgement.measured = Measured::Partial {
        issues: vec![MeasureIssue::Clipped, MeasureIssue::ColdStartRegister],
    };
    let a = fuse_syllable(&f, &[], &seed());
    assert_eq!(a.expected, ToneId("4".into()));
    assert_eq!(a.distance, Some(1.25));
    assert_eq!(a.component.as_deref(), Some("cmn-TW/t3-low"));
    assert_eq!(a.deltas, f.judgement.deltas);
    assert_eq!(a.measured, f.judgement.measured);
}

// ---------------------------------------------------------------------------------------------
// assemble.
// ---------------------------------------------------------------------------------------------

#[test]
fn assemble_fills_the_envelope() {
    let r = decoded(vec![cand("a", 2.0, vec![fit(0.0, Measured::Full)])], -1.0);
    let accents = vec![
        AccentFit {
            accent: AccentId("cmn-standard".into()),
            llr: 1.5,
        },
        AccentFit {
            accent: AccentId("cmn-TW".into()),
            llr: -0.5,
        },
    ];
    let out = assemble(&r, &id("a"), &[], &seed(), accents.clone(), register()).unwrap();
    assert_eq!(out.schema, "tonekit.assessment.v1");
    assert_eq!(out.intended, id("a"));
    assert_eq!(out.accent_fit, accents);
    assert_eq!(out.register_update, register());
    assert_eq!(out.syllables.len(), 1);
}

#[test]
fn rank_is_one_based_position_in_candidates() {
    let mk = |name: &str, llr: f32| cand(name, llr, vec![fit(0.0, Measured::Full)]);
    let r = decoded(vec![mk("a", 4.0), mk("b", 3.0), mk("c", 1.0)], 0.0);
    assert_eq!(run(&r, "a", &[]).unwrap().intended_rank, 1);
    assert_eq!(run(&r, "b", &[]).unwrap().intended_rank, 2);
    assert_eq!(run(&r, "c", &[]).unwrap().intended_rank, 3);
}

#[test]
fn margin_is_against_the_best_other_candidate_or_null() {
    let mk = |name: &str, llr: f32| cand(name, llr, vec![fit(0.0, Measured::Full)]);
    let r = decoded(vec![mk("a", 4.0), mk("b", 3.0), mk("c", 1.0)], 0.0);
    // Intended first: best other is "b" (3.0).
    assert_abs_diff_eq!(run(&r, "a", &[]).unwrap().margin_llr, 1.0, epsilon = 1e-6);
    // Intended in the middle: best other is "a" (4.0), not the nearest neighbour.
    assert_abs_diff_eq!(run(&r, "b", &[]).unwrap().margin_llr, -1.0, epsilon = 1e-6);
    // Intended last.
    assert_abs_diff_eq!(run(&r, "c", &[]).unwrap().margin_llr, -3.0, epsilon = 1e-6);

    // The null competitor wins over a weaker rival ...
    let r = decoded(vec![mk("a", 4.0), mk("b", 1.0)], 2.5);
    assert_abs_diff_eq!(run(&r, "a", &[]).unwrap().margin_llr, 1.5, epsilon = 1e-6);
    // ... and a negative null_llr does not lift a below-null margin.
    let r = decoded(vec![mk("a", 4.0), mk("b", 3.0)], -10.0);
    assert_abs_diff_eq!(run(&r, "a", &[]).unwrap().margin_llr, 1.0, epsilon = 1e-6);
}

#[test]
fn margin_with_no_other_candidates_is_against_null() {
    let r = decoded(vec![cand("a", 2.0, vec![fit(0.0, Measured::Full)])], 0.5);
    let out = run(&r, "a", &[]).unwrap();
    assert_eq!(out.intended_rank, 1);
    assert_abs_diff_eq!(out.margin_llr, 1.5, epsilon = 1e-6);
}

#[test]
fn intended_candidate_missing_is_a_pack_error() {
    let r = decoded(vec![cand("a", 2.0, vec![fit(0.0, Measured::Full)])], 0.0);
    assert_eq!(
        run(&r, "nope", &[]),
        Err(AssessError::Pack {
            message: "intended candidate missing".into()
        })
    );
    let empty = decoded(vec![], 0.0);
    assert_eq!(
        run(&empty, "a", &[]),
        Err(AssessError::Pack {
            message: "intended candidate missing".into()
        })
    );
}

#[test]
fn empty_external_means_acoustic_only() {
    let r = decoded(
        vec![cand(
            "a",
            1.0,
            vec![fit(2.0, Measured::Full), fit(-1.0, Measured::Full)],
        )],
        0.0,
    );
    let out = run(&r, "a", &[]).unwrap();
    assert_abs_diff_eq!(out.syllables[0].p_correct, sigmoid(2.0), epsilon = 1e-6);
    assert_abs_diff_eq!(out.syllables[1].p_correct, sigmoid(-1.0), epsilon = 1e-6);
    for s in &out.syllables {
        assert_eq!(s.basis, vec![EvidenceKind::Acoustic]);
    }
}

#[test]
fn external_evidence_is_matched_to_syllables_by_position() {
    let r = decoded(
        vec![cand(
            "a",
            1.0,
            vec![fit(1.0, Measured::Full), fit(1.0, Measured::Full)],
        )],
        0.0,
    );
    let external = vec![vec![confusion("2", "谁")], vec![transcript(true)]];
    let out = run(&r, "a", &external).unwrap();
    assert!(out.syllables[0].p_correct <= 0.05);
    assert_eq!(out.syllables[0].heard_as.as_deref(), Some("谁"));
    assert_abs_diff_eq!(out.syllables[1].p_correct, sigmoid(1.5), epsilon = 1e-6);
    assert_eq!(out.syllables[1].heard_as, None);
    // The veto drags the utterance down.
    assert_eq!(out.overall, Some(out.syllables[0].p_correct));
}

#[test]
fn per_syllable_empty_evidence_is_allowed() {
    let r = decoded(
        vec![cand(
            "a",
            1.0,
            vec![fit(1.0, Measured::Full), fit(1.0, Measured::Full)],
        )],
        0.0,
    );
    let out = run(&r, "a", &[vec![], vec![]]).unwrap();
    assert_abs_diff_eq!(out.syllables[1].p_correct, sigmoid(1.0), epsilon = 1e-6);
}

#[test]
fn evidence_length_mismatch_too_many_and_uses_the_intended_candidates_count() {
    let r = decoded(
        vec![
            cand(
                "long",
                3.0,
                vec![
                    fit(0.0, Measured::Full),
                    fit(0.0, Measured::Full),
                    fit(0.0, Measured::Full),
                ],
            ),
            cand("short", 1.0, vec![fit(0.0, Measured::Full)]),
        ],
        0.0,
    );
    // Intended = "short" (1 syllable): 3 evidence entries is too many.
    assert_eq!(
        run(&r, "short", &[vec![], vec![], vec![]]),
        Err(AssessError::EvidenceLengthMismatch {
            expected: 1,
            got: 3
        })
    );
    // Intended = "long" (3 syllables): the right count is accepted.
    assert!(run(&r, "long", &[vec![], vec![], vec![]]).is_ok());
    // One entry per syllable is required, not one in total.
    assert_eq!(
        run(&r, "long", &[vec![]]),
        Err(AssessError::EvidenceLengthMismatch {
            expected: 3,
            got: 1
        })
    );
}

#[test]
fn overall_ignores_unmeasured_syllables() {
    // An unmeasured syllable reads p = 0.5, which must not pull a confident utterance down.
    let r = decoded(
        vec![cand(
            "a",
            1.0,
            vec![
                fit(logit(0.9), Measured::Full),
                fit(-3.0, unmeasured()),
                fit(
                    logit(0.7),
                    Measured::Partial {
                        issues: vec![MeasureIssue::LowSnr],
                    },
                ),
            ],
        )],
        0.0,
    );
    let out = run(&r, "a", &[]).unwrap();
    assert_abs_diff_eq!(out.syllables[1].p_correct, 0.5, epsilon = 1e-6);
    // Partial counts as measured; the unmeasured 0.5 is skipped, so the minimum is 0.7.
    assert_abs_diff_eq!(out.overall.unwrap(), 0.7, epsilon = 1e-5);
}

#[test]
fn candidate_with_no_syllables_has_no_overall() {
    let r = decoded(vec![cand("a", 0.0, vec![])], 0.0);
    let out = run(&r, "a", &[]).unwrap();
    assert!(out.syllables.is_empty());
    assert_eq!(out.overall, None);
}
