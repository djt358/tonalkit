//! Closed-set decoding and the open tone lattice (spec §7.2–7.3), end to end on synthetic speech.
//!
//! Utterances are synthesised by `tonekit-testkit` and analysed with the real upstream stages
//! (pYIN, octave repair, energy, speech region, nuclei, boundaries). Tones are realised as Task 10
//! will speak them (ruling R8): "1" → [5,5], "2" → [3,5], "3" → [2,1,4] when phrase-final and
//! [2,1] otherwise, "4" → [5,1].

use tonekit_core::{
    AccentId, Analysis, AssessError, Candidate, CandidateId, EnergyTrack, F0Frame, F0Track,
    GradingTarget, MeasureIssue, Measured, RegisterSource, ToneId, ToneTarget, WeightedTone,
};
use tonekit_decode::{decode, lattice};
use tonekit_f0::{energy, repair_octaves, F0Provider, Pyin};
use tonekit_pack::LanguagePack;
use tonekit_segment::{boundaries, nuclei, speech_frames, speech_region, SegmentParams};
use tonekit_shape::voiced_semitones;
use tonekit_testkit::{register_for, synth, SynthSpec, SynthSyllable};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");

fn cmn() -> LanguagePack {
    LanguagePack::from_toml(CMN_TOML, Some(CMN_CALIB)).unwrap()
}

fn std_g() -> GradingTarget {
    GradingTarget {
        accent: AccentId("cmn-standard".into()),
        style: None,
        style_weight: 0.0,
    }
}

/// One 250 ms syllable per entry (Chao knots), 60 ms of silence after each, no unvoiced onset or
/// creak, floor 100 Hz / ceiling 200 Hz, 200 ms lead and tail, seed 1.
fn three(sylls: Vec<Vec<f32>>) -> SynthSpec {
    SynthSpec {
        floor_hz: 100.0,
        ceil_hz: 200.0,
        lead_ms: 200.0,
        tail_ms: 200.0,
        syllables: sylls
            .into_iter()
            .map(|chao| SynthSyllable {
                chao,
                dur_ms: 250.0,
                gap_after_ms: 60.0,
                unvoiced_onset_ms: 0.0,
                creak: None,
            })
            .collect(),
        snr_db: None,
        seed: 1,
    }
}

/// The analysis the facade (Task 10) will build, from the real upstream stages with default
/// segmentation parameters and the speaker's exact, warm register.
fn analysis_of(spec: &SynthSpec) -> Analysis {
    let s = synth(spec);
    let mut f0 = Pyin::default().track(&s.pcm);
    repair_octaves(&mut f0);
    let e = energy(&s.pcm);
    let p = SegmentParams::default();
    let speech = speech_region(&e, &p);
    let (nuclei, boundaries) = match &speech {
        Some(region) => {
            let n = nuclei(&e, &f0, region, &p);
            let b = boundaries(&e, &f0, region, &n);
            (n, b)
        }
        None => (Vec::new(), Vec::new()),
    };
    let voiced_st = voiced_semitones(&f0, speech.as_ref());
    Analysis {
        f0,
        energy: e,
        nuclei,
        boundaries,
        speech,
        register: register_for(100.0, 200.0),
        register_source: RegisterSource::Given,
        voiced_st,
        issues: Vec::new(),
        sonority: Vec::new(),
    }
}

/// A hand-built analysis of `frames` frames of digital silence: no speech, nuclei or boundaries.
/// For the error tests, which never reach the audio.
fn quiet(frames: usize) -> Analysis {
    Analysis {
        f0: F0Track {
            frames: vec![
                F0Frame {
                    hz: None,
                    voiced_p: 0.0,
                };
                frames
            ],
            provider: "hand".into(),
        },
        energy: EnergyTrack {
            db: vec![-100.0; frames],
        },
        nuclei: Vec::new(),
        boundaries: Vec::new(),
        speech: None,
        register: register_for(100.0, 200.0),
        register_source: RegisterSource::Given,
        voiced_st: Vec::new(),
        issues: Vec::new(),
        sonority: Vec::new(),
    }
}

fn target(tone: &str) -> ToneTarget {
    ToneTarget {
        tone: ToneId(tone.into()),
        lexical_variants: Vec::new(),
        label: None,
    }
}

/// A candidate whose targets carry no lexical variants.
fn c(id: &str, tones: &[&str]) -> Candidate {
    Candidate {
        id: CandidateId(id.into()),
        targets: tones.iter().map(|t| target(t)).collect(),
    }
}

fn argmax(v: &[f32]) -> usize {
    (0..v.len())
        .max_by(|&a, &b| v[a].total_cmp(&v[b]))
        .expect("non-empty")
}

fn tone_index(pack: &LanguagePack, tone: &str) -> usize {
    pack.inventory()
        .iter()
        .position(|t| t.0 == tone)
        .expect("tone in inventory")
}

// --- The brief's tests ------------------------------------------------------------------------

#[test]
fn picks_intended_among_tone_minimal_pairs() {
    // 买 mǎi vs 卖 mài pattern: 3-1-4 spoken, with the non-final T3 as a half third (R8).
    let a = analysis_of(&three(vec![vec![2., 1.], vec![5., 5.], vec![5., 1.]]));
    let r = decode(
        &a,
        &cmn(),
        &std_g(),
        &[
            c("a", &["3", "1", "4"]),
            c("b", &["4", "1", "4"]),
            c("c", &["3", "1", "2"]),
        ],
    )
    .unwrap();
    assert_eq!(r.candidates[0].id.0, "a");
}

#[test]
fn candidates_of_different_lengths_compete() {
    let a = analysis_of(&three(vec![vec![5., 1.], vec![5., 5.], vec![2., 1., 4.]]));
    let r = decode(
        &a,
        &cmn(),
        &std_g(),
        &[
            c("two", &["4", "1"]),
            c("three", &["4", "1", "3"]),
            c("four", &["4", "1", "3", "4"]),
        ],
    )
    .unwrap();
    assert_eq!(r.candidates[0].id.0, "three");
}

#[test]
fn leading_filler_syllable_does_not_shift_tones() {
    // 嗯 + 4-1-3: the hesitation is absorbed as an insertion (R33), not matched to the first
    // target.
    let a = analysis_of(&three(vec![
        vec![3., 3.],
        vec![5., 1.],
        vec![5., 5.],
        vec![2., 1., 4.],
    ]));
    let r = decode(&a, &cmn(), &std_g(), &[c("spell", &["4", "1", "3"])]).unwrap();
    let s = &r.candidates[0].syllables;
    assert_eq!(s.len(), 3);
    assert!(s.iter().all(|f| f.judgement.llr_target > 0.0), "{s:#?}");
    // And the syllables sit on the spoken 4-1-3, after the filler (which ends near frame 45)...
    assert!(s[0].span.start_frame >= 45, "{:?}", s[0].span);
    // ...whose nucleus no syllable holds.
    assert_eq!(a.nuclei.len(), 4, "{:?}", a.nuclei);
    assert!(a.nuclei[0].frame < 45, "{:?}", a.nuclei);
}

#[test]
fn wrong_tones_lose_to_null() {
    let a = analysis_of(&three(vec![vec![5., 5.], vec![5., 5.], vec![5., 5.]]));
    let r = decode(&a, &cmn(), &std_g(), &[c("x", &["4", "4", "4"])]).unwrap();
    assert!(r.null_posterior > r.candidates[0].posterior);
}

#[test]
fn lattice_recovers_tones_and_sums_to_one() {
    let pack = cmn();
    let a = analysis_of(&three(vec![vec![3., 5.], vec![5., 1.], vec![5., 5.]]));
    let l = lattice(&a, &pack, &std_g()).unwrap();
    assert_eq!(l.tbus.len(), 3);
    assert_eq!(l.schema, "tonekit.lattice.v1");
    for (tbu, want) in l.tbus.iter().zip(["2", "4", "1"]) {
        let best = argmax(&tbu.posterior);
        assert_eq!(l.inventory[best].0, want, "{tbu:#?}");
        approx::assert_abs_diff_eq!(tbu.posterior.iter().sum::<f32>(), 1.0, epsilon = 1e-4);
    }
    // The pack's metadata travels with the lattice.
    assert_eq!(l.lect, *pack.lect());
    assert_eq!(l.accent, std_g().accent);
    assert_eq!(l.inventory, pack.inventory());
    assert_eq!(l.prior, pack.prior());
}

#[test]
fn neutral_tone_context_is_used() {
    // T3 (non-final: a half third, [2,1]) then a neutral tone realised at Chao 4, which is what
    // the pack expects of "5" after "3" and nothing else in the inventory.
    let pack = cmn();
    let a = analysis_of(&three(vec![vec![2., 1.], vec![4.]]));
    let l = lattice(&a, &pack, &std_g()).unwrap();
    assert_eq!(l.tbus.len(), 2);
    let second = &l.tbus[1];
    assert_eq!(argmax(&second.posterior), tone_index(&pack, "5"), "{l:#?}");
}

#[test]
fn no_speech_gives_unmeasured_candidates() {
    let pack = cmn();
    let a = analysis_of(&three(vec![]));
    assert!(a.speech.is_none());
    let unvoiced = pack.calibration().decode.unvoiced_syllable_llr;
    let r = decode(
        &a,
        &pack,
        &std_g(),
        &[c("one", &["1"]), c("three", &["4", "1", "3"])],
    )
    .unwrap();
    assert_eq!(r.candidates.len(), 2);
    for cand in &r.candidates {
        let k = if cand.id.0 == "one" { 1 } else { 3 };
        assert_eq!(cand.syllables.len(), k);
        assert_eq!(cand.llr, k as f32 * unvoiced);
        for s in &cand.syllables {
            assert_eq!(
                s.judgement.measured,
                Measured::NotMeasured {
                    issue: MeasureIssue::Unvoiced
                }
            );
            assert_eq!((s.span.start_frame, s.span.end_frame), (0, 0));
            assert_eq!(s.judgement.llr_target, unvoiced);
        }
    }
    assert_eq!(r.null_llr, 0.0);
}

#[test]
fn too_few_boundaries_gives_missed_syllables_at_the_region_start() {
    // One spoken syllable cannot hold eight: that candidate has no complete path, even relaxed.
    // The utterance has a nucleus, so its syllables are likely misses (R33), not "not checked".
    let pack = cmn();
    let unvoiced = pack.calibration().decode.unvoiced_syllable_llr;
    let a = analysis_of(&three(vec![vec![5., 5.]]));
    let start = a.speech.as_ref().unwrap().start;
    let r = decode(
        &a,
        &pack,
        &std_g(),
        &[c("eight", &["1"; 8]), c("one", &["1"])],
    )
    .unwrap();
    assert_eq!(r.candidates[0].id.0, "one");
    let eight = &r.candidates[1];
    assert_eq!(eight.llr, 8.0 * unvoiced);
    assert_eq!(eight.syllables.len(), 8);
    for s in &eight.syllables {
        assert_eq!((s.span.start_frame, s.span.end_frame), (start, start));
        assert_eq!(
            s.judgement.measured,
            Measured::Partial {
                issues: vec![MeasureIssue::NoNucleus]
            }
        );
        assert_eq!(s.judgement.expected.0, "1");
        assert_eq!(s.judgement.llr_target, unvoiced);
    }
}

#[test]
fn unknown_tone_errors() {
    let r = decode(&quiet(40), &cmn(), &std_g(), &[c("x", &["1", "9"])]);
    assert_eq!(
        r,
        Err(AssessError::UnknownTone {
            tone: ToneId("9".into())
        })
    );
}

// --- Input validation -------------------------------------------------------------------------

#[test]
fn unknown_lexical_variant_tone_errors() {
    let mut cand = c("x", &["1"]);
    cand.targets[0].lexical_variants.push(WeightedTone {
        tone: ToneId("7".into()),
        weight: 0.2,
    });
    let r = decode(&quiet(40), &cmn(), &std_g(), &[cand]);
    assert_eq!(
        r,
        Err(AssessError::UnknownTone {
            tone: ToneId("7".into())
        })
    );
}

#[test]
fn duplicate_candidate_ids_error() {
    let r = decode(
        &quiet(40),
        &cmn(),
        &std_g(),
        &[c("x", &["1"]), c("y", &["2"]), c("x", &["3"])],
    );
    assert_eq!(
        r,
        Err(AssessError::DuplicateCandidate {
            id: CandidateId("x".into())
        })
    );
}

#[test]
fn empty_candidate_set_and_empty_candidate_are_invalid_requests() {
    let a = quiet(40);
    assert_eq!(
        decode(&a, &cmn(), &std_g(), &[]),
        Err(AssessError::InvalidRequest {
            message: "empty candidate set".into()
        })
    );
    assert_eq!(
        decode(&a, &cmn(), &std_g(), &[c("x", &["1"]), c("nil", &[])]),
        Err(AssessError::InvalidRequest {
            message: "candidate nil has no targets".into()
        })
    );
}

#[test]
fn grading_errors_surface_even_without_speech() {
    let mut g = std_g();
    g.accent = AccentId("cmn-XX".into());
    let pack = cmn();
    let d = decode(&quiet(40), &pack, &g, &[c("x", &["1"])]);
    assert!(matches!(d, Err(AssessError::Pack { ref message }) if message.contains("cmn-XX")));
    let l = lattice(&quiet(40), &pack, &g);
    assert!(matches!(l, Err(AssessError::Pack { ref message }) if message.contains("cmn-XX")));

    // Lexical variants that outweigh the main tone are a pack (expectation) error.
    let mut cand = c("x", &["1"]);
    cand.targets[0].lexical_variants.push(WeightedTone {
        tone: ToneId("2".into()),
        weight: 1.5,
    });
    let d = decode(&quiet(40), &pack, &std_g(), &[cand]);
    assert!(matches!(d, Err(AssessError::Pack { .. })), "{d:?}");
}

// --- Result shape -----------------------------------------------------------------------------

#[test]
fn results_are_sorted_normalised_and_finite() {
    let a = analysis_of(&three(vec![vec![2., 1.], vec![5., 5.], vec![5., 1.]]));
    let cands = [
        c("c", &["3", "1", "2"]),
        c("a", &["3", "1", "4"]),
        c("one", &["1"]),
        c("b", &["4", "1", "4"]),
        c("five", &["3", "1", "4", "4", "4"]),
    ];
    let r = decode(&a, &cmn(), &std_g(), &cands).unwrap();
    assert_eq!(r.candidates.len(), cands.len());
    for pair in r.candidates.windows(2) {
        assert!(pair[0].llr >= pair[1].llr);
    }
    let total: f32 = r.candidates.iter().map(|s| s.posterior).sum::<f32>() + r.null_posterior;
    approx::assert_abs_diff_eq!(total, 1.0, epsilon = 1e-5);
    assert!(r.null_llr >= 0.0 && r.null_llr.is_finite());
    for cand in &r.candidates {
        assert!(cand.llr.is_finite() && cand.posterior.is_finite());
        let k = cands
            .iter()
            .find(|x| x.id == cand.id)
            .unwrap()
            .targets
            .len();
        assert_eq!(cand.syllables.len(), k);
        // Syllables are in order and do not overlap.
        for pair in cand.syllables.windows(2) {
            assert!(pair[0].span.end_frame <= pair[1].span.start_frame);
        }
        for s in &cand.syllables {
            let j = &s.judgement;
            assert!(j.llr_target.is_finite());
            assert!(j.loglik.iter().all(|v| v.is_finite()));
        }
    }
}

#[test]
fn a_single_candidate_is_the_known_count_case() {
    // A set of size one is v1's "known N": the decoder still places each syllable on its own.
    // Task 10's spoken(4-1-3), restored now that R32 measures its initial fall.
    let a = analysis_of(&three(vec![vec![5., 1.], vec![5., 5.], vec![2., 1., 4.]]));
    let r = decode(&a, &cmn(), &std_g(), &[c("spell", &["4", "1", "3"])]).unwrap();
    let s = &r.candidates[0].syllables;
    for (fit, tone) in s.iter().zip(["4", "1", "3"]) {
        assert_eq!(fit.judgement.expected.0, tone);
        assert!(fit.judgement.llr_target > 0.0, "{fit:#?}");
        assert!(matches!(fit.judgement.measured, Measured::Full));
    }
    // Each syllable lands on its spoken one (frames 20-45, 51-76, 82-107), give or take the half
    // of the 6-frame pause up to the boundary between the nuclei.
    let spoken = [(20, 45), (51, 76), (82, 107)];
    for (fit, (start, end)) in s.iter().zip(spoken) {
        assert!(fit.span.start_frame.abs_diff(start) <= 3, "{:?}", fit.span);
        assert!(fit.span.end_frame.abs_diff(end) <= 3, "{:?}", fit.span);
    }
    assert!(r.candidates[0].posterior > r.null_posterior);
}

#[test]
fn candidate_llr_is_its_tone_evidence_plus_the_best_placement() {
    // llr = Σ judge's llr_target (each on the shape of the nucleus the syllable holds, reported at
    // that nucleus's TBU, R50) + the best placement of the syllables on boundary pairs, which only
    // the accounting decides: Σ dur(pair) − filler_per_frame × speech frames outside syllables +
    // insertion_llr × nuclei outside syllables, with dur = −(ln(d/r))²/(2σ²) and r the median
    // inter-nucleus interval, each pair a 60–800 ms span holding its syllable's nucleus and no
    // other. The placement is found here by trying every one.
    let pack = cmn();
    let d = pack.calibration().decode.clone();
    let a = analysis_of(&three(vec![
        vec![3., 3.],
        vec![5., 1.],
        vec![5., 5.],
        vec![2., 1., 4.],
    ]));
    let mut mixed = c("mixed", &["4", "1", "3"]);
    mixed.targets[2].lexical_variants.push(WeightedTone {
        tone: ToneId("2".into()),
        weight: 0.3,
    });
    let cands = [
        c("spell", &["4", "1", "3"]),
        mixed,
        c("long", &["2", "4", "1", "3"]),
        c("short", &["1"]),
    ];
    let r = decode(&a, &pack, &std_g(), &cands).unwrap();
    let l = lattice(&a, &pack, &std_g()).unwrap();

    let is_speech = speech_frames(&a.energy, &SegmentParams::default());
    let speech = |from: u32, to: u32| (from..to).filter(|&f| is_speech[f as usize]).count() as f64;
    let mut frames: Vec<u32> = a.nuclei.iter().map(|n| n.frame).collect();
    frames.sort_unstable();
    let mut gaps: Vec<u32> = frames.windows(2).map(|w| w[1] - w[0]).collect();
    gaps.sort_unstable();
    assert_eq!(gaps.len() % 2, 1, "{frames:?}");
    let rate_s = f64::from(gaps[gaps.len() / 2]) * 0.01;
    let sigma = f64::from(d.dur_sigma);
    let dur = |frames: u32| {
        let x = (f64::from(frames) * 0.01 / rate_s).ln();
        -x * x / (2.0 * sigma * sigma)
    };
    let (filler, insertion) = (f64::from(d.filler_per_frame), f64::from(d.insertion_llr));
    let n_frames = a.energy.db.len() as u32;
    let nuclei = |from: u32, to: u32| frames.iter().filter(|&&f| from <= f && f < to).count();
    let left_over =
        |from: u32, to: u32| -filler * speech(from, to) + insertion * nuclei(from, to) as f64;
    let mut bounds = a.boundaries.clone();
    bounds.sort_unstable();
    bounds.dedup();

    /// The best score of placing syllables `k..` (each on one of its `options`) from frame `at`.
    fn place(
        k: usize,
        at: u32,
        options: &[Vec<(u32, u32)>],
        score: &dyn Fn(u32, u32) -> f64,
        left_over: &dyn Fn(u32, u32) -> f64,
        end: u32,
    ) -> f64 {
        if k == options.len() {
            return left_over(at, end);
        }
        options[k]
            .iter()
            .filter(|&&(from, _)| from >= at)
            .map(|&(from, to)| {
                left_over(at, from)
                    + score(from, to)
                    + place(k + 1, to, options, score, left_over, end)
            })
            .fold(f64::NEG_INFINITY, f64::max)
    }

    for cand in &r.candidates {
        // Each syllable sits at the TBU of a distinct nucleus, and is judged on its shape.
        let held: Vec<u32> = cand
            .syllables
            .iter()
            .map(|s| {
                let tbu = l.tbus.iter().position(|t| t.span == s.span).expect("a TBU");
                assert_eq!(nuclei(s.span.start_frame, s.span.end_frame), 1);
                frames[tbu]
            })
            .collect();
        assert!(held.windows(2).all(|w| w[0] < w[1]), "{}", cand.id.0);
        let options: Vec<Vec<(u32, u32)>> = held
            .iter()
            .map(|&f| {
                let mut pairs = Vec::new();
                for (i, &from) in bounds.iter().enumerate() {
                    for &to in &bounds[i + 1..] {
                        let ok = from <= f && f < to && nuclei(from, to) == 1;
                        if ok && (6..=80).contains(&(to - from)) {
                            pairs.push((from, to));
                        }
                    }
                }
                pairs
            })
            .collect();
        let evidence: f64 = cand
            .syllables
            .iter()
            .map(|s| f64::from(s.judgement.llr_target))
            .sum();
        let score = |from: u32, to: u32| dur(to - from);
        let want = evidence + place(0, 0, &options, &score, &left_over, n_frames);
        approx::assert_abs_diff_eq!(f64::from(cand.llr), want, epsilon = 1e-4);
    }
    // The hesitation's nucleus is an insertion for the three-syllable spellings.
    let spell = r.candidates.iter().find(|x| x.id.0 == "spell").unwrap();
    assert!(
        frames[0] < spell.syllables[0].span.start_frame,
        "{frames:?} {spell:#?}"
    );
    // A lexical variant widens the target without losing the spoken 4-1-3.
    let m = r.candidates.iter().find(|x| x.id.0 == "mixed").unwrap();
    assert!(
        m.syllables.iter().all(|f| f.judgement.llr_target > 0.0),
        "{m:#?}"
    );
}

// --- Ruling R32: a voiced frame is `hz.is_some()` ---------------------------------------------

#[test]
fn the_initial_fall_of_spoken_4_1_3_scores_as_a_4() {
    // Before R32 only 4 of this fall's 25 frames counted as voiced (voiced_p >= 0.5), one of them
    // octave-doubled by the repair, and "4" scored llr −13.8 on it. With pYIN's own voicing it is
    // a clean fall, and "4" is the tone it supports.
    let pack = cmn();
    let a = analysis_of(&three(vec![vec![5., 1.], vec![5., 5.], vec![2., 1., 4.]]));
    let (start_frame, end_frame) = synth(&three(vec![vec![5., 1.]])).syllable_frames[0];
    let span = tonekit_core::TbuSpan {
        start_frame,
        end_frame,
    };
    let ex = tonekit_shape::extract(&a.f0, &span, &a.register).expect("the fall is voiced");
    let c = &ex.shape.contour;
    assert!(c[0] > c[9] + 3.0 && ex.shape.slope < 0.0, "{c:?}");
    let ctx = tonekit_pack::TargetContext {
        index: 0,
        count: 3,
        prev: None,
        phrase_final: false,
    };
    let j = pack
        .judge(&std_g(), &ex.shape, &target("4"), &ctx, &ex.issues)
        .unwrap();
    assert!(j.llr_target > 0.0, "{j:#?}");
    assert_eq!(j.heard, Some(ToneId("4".into())), "{j:#?}");
}

// --- Ruling R33: syllables are anchored on nuclei ----------------------------------------------

#[test]
fn a_wrong_final_tone_is_judged_on_the_whole_syllable() {
    // spoken 4-1-4 (and 4-1-1) against intended 4-1-3: the "3" cannot hide on the unvoiced pause
    // before the last syllable or on the low tail of a final fall; it sits on the whole final
    // syllable (frames 82-107) and scores clearly negative, below even an unmeasured syllable.
    let pack = cmn();
    let unvoiced = pack.calibration().decode.unvoiced_syllable_llr;
    for last in [vec![5., 1.], vec![5., 5.]] {
        let a = analysis_of(&three(vec![vec![5., 1.], vec![5., 5.], last.clone()]));
        let r = decode(&a, &pack, &std_g(), &[c("intended", &["4", "1", "3"])]).unwrap();
        let s = &r.candidates[0].syllables;
        let three = &s[2];
        assert_eq!(three.judgement.expected.0, "3");
        assert!(
            three.span.start_frame <= 82 && three.span.end_frame >= 107,
            "{last:?}: {three:#?}"
        );
        assert!(
            matches!(three.judgement.measured, Measured::Full),
            "{three:#?}"
        );
        assert!(
            three.judgement.llr_target < unvoiced,
            "{last:?}: {three:#?}"
        );
        // The first two are right, and measured as such.
        for fit in &s[..2] {
            assert!(fit.judgement.llr_target > 0.0, "{fit:#?}");
        }
        // Losing to the null: this is not what was said.
        assert!(r.null_posterior > r.candidates[0].posterior, "{r:#?}");
    }
}

#[test]
fn a_dropped_syllable_is_a_likely_miss_not_unmeasured() {
    // Two voiced syllables (4, 3) against a three-target candidate (4-1-3): no strict path, so
    // the relaxed pass puts one target on a span without a nucleus. It scores the unvoiced LLR and
    // is `Partial { [NoNucleus] }`, so it counts towards `overall` as a miss.
    let pack = cmn();
    let unvoiced = pack.calibration().decode.unvoiced_syllable_llr;
    let a = analysis_of(&three(vec![vec![5., 1.], vec![2., 1., 4.]]));
    assert_eq!(a.nuclei.len(), 2, "{:?}", a.nuclei);
    let r = decode(&a, &pack, &std_g(), &[c("spell", &["4", "1", "3"])]).unwrap();
    let s = &r.candidates[0].syllables;
    assert_eq!(s.len(), 3);
    let missed = Measured::Partial {
        issues: vec![MeasureIssue::NoNucleus],
    };
    assert!(
        s.iter()
            .all(|f| !matches!(f.judgement.measured, Measured::NotMeasured { .. })),
        "{s:#?}"
    );
    let misses: Vec<&str> = s
        .iter()
        .filter(|f| f.judgement.measured == missed)
        .map(|f| f.judgement.expected.0.as_str())
        .collect();
    assert_eq!(misses, ["1"], "{s:#?}");
    let one = &s[1];
    assert_eq!(one.judgement.llr_target, unvoiced);
    assert!(one.judgement.loglik.is_empty() && one.judgement.heard.is_none());
    // The spoken 4 and 3 keep their syllables.
    assert!(
        s[0].judgement.llr_target > 0.0 && s[2].judgement.llr_target > 0.0,
        "{s:#?}"
    );
    // The reported spans run in time order without overlapping, the dropped syllable's included
    // (R55; the gap it keeps is clipped to its neighbours' TBUs).
    for fit in s {
        assert!(fit.span.start_frame <= fit.span.end_frame, "{s:#?}");
    }
    for pair in s.windows(2) {
        assert!(pair[0].span.end_frame <= pair[1].span.start_frame, "{s:#?}");
    }
}

#[test]
fn whisper_has_no_nuclei_and_is_not_measured() {
    // Whispered 4-1-3: speech, but no periodicity, so no nuclei; nothing can be anchored and every
    // syllable is NotMeasured ("tone not checked"), at the start of the speech region.
    let pack = cmn();
    let unvoiced = pack.calibration().decode.unvoiced_syllable_llr;
    let mut spec = three(vec![vec![5., 1.], vec![5., 5.], vec![2., 1., 4.]]);
    for s in &mut spec.syllables {
        s.unvoiced_onset_ms = s.dur_ms;
    }
    let a = analysis_of(&spec);
    let start = a.speech.as_ref().expect("whisper is speech").start;
    assert!(a.nuclei.is_empty(), "{:?}", a.nuclei);
    let r = decode(&a, &pack, &std_g(), &[c("spell", &["4", "1", "3"])]).unwrap();
    let cand = &r.candidates[0];
    assert_eq!(cand.llr, 3.0 * unvoiced);
    for s in &cand.syllables {
        assert_eq!(
            s.judgement.measured,
            Measured::NotMeasured {
                issue: MeasureIssue::Unvoiced
            }
        );
        assert_eq!((s.span.start_frame, s.span.end_frame), (start, start));
    }
    assert_eq!(r.null_llr, 0.0);
}

// --- Ruling R50: one shape per nucleus, for every candidate ------------------------------------

#[test]
fn every_candidate_is_judged_on_the_shapes_the_lattice_reports() {
    // Spoken 4-1-3. Right or wrong, each reading is judged on the shape the lattice reports for
    // the nucleus under each syllable: no target gets to choose the frames that suit it, so a
    // wrong tone scores against the syllable as spoken.
    let pack = cmn();
    let a = analysis_of(&three(vec![vec![5., 1.], vec![5., 5.], vec![2., 1., 4.]]));
    let l = lattice(&a, &pack, &std_g()).unwrap();
    assert_eq!(l.tbus.len(), 3);
    let cands = [
        c("413", &["4", "1", "3"]),
        c("423", &["4", "2", "3"]),
        c("213", &["2", "1", "3"]),
        c("414", &["4", "1", "4"]),
    ];
    let r = decode(&a, &pack, &std_g(), &cands).unwrap();
    let llr = |id: &str, k: usize| {
        let cand = r.candidates.iter().find(|x| x.id.0 == id).unwrap();
        cand.syllables[k].judgement.llr_target
    };
    for cand in &r.candidates {
        let targets = &cands.iter().find(|x| x.id == cand.id).unwrap().targets;
        for (k, (fit, tbu)) in cand.syllables.iter().zip(&l.tbus).enumerate() {
            let ctx = tonekit_pack::TargetContext {
                index: k as u32,
                count: 3,
                prev: k.checked_sub(1).map(|p| targets[p].tone.clone()),
                phrase_final: k == 2,
            };
            let shape = tbu.shape.as_ref().expect("every syllable is voiced");
            let want = pack.judge(&std_g(), shape, &targets[k], &ctx, &[]).unwrap();
            assert_eq!(fit.judgement, want, "{} syllable {k}", cand.id.0);
            assert_eq!(fit.span, tbu.span, "{} syllable {k}", cand.id.0);
        }
    }
    // The substituted syllables score against the background, below the spoken tones.
    for (id, k) in [("423", 1), ("213", 0), ("414", 2)] {
        assert!(
            llr(id, k) < 0.0 && llr(id, k) < llr("413", k),
            "{id}: {r:#?}"
        );
    }
}
