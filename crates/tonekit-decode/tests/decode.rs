//! Closed-set decoding and the open tone lattice (spec §7.2–7.3), end to end on synthetic speech.
//!
//! Utterances are synthesised by `tonekit-testkit` and analysed with the real upstream stages
//! (pYIN, octave repair, energy, speech region, nuclei, boundaries). Tones are realised as Task 10
//! will speak them (ruling R8): "1" → [5,5], "2" → [3,5], "3" → [2,1,4] when phrase-final and
//! [2,1] otherwise, "4" → [5,1].

use tonekit_core::{
    AccentId, Analysis, AssessError, Candidate, CandidateId, EnergyTrack, F0Frame, F0Track,
    GradingTarget, Measured, RegisterSource, ToneId, ToneTarget, WeightedTone,
};
use tonekit_decode::{decode, lattice};
use tonekit_f0::{energy, repair_octaves, F0Provider, Pyin};
use tonekit_pack::LanguagePack;
use tonekit_segment::{boundaries, nuclei, speech_region, speech_threshold, SegmentParams};
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
    // 嗯 + 4-1-3: the hesitation is absorbed as filler, not matched to the first target.
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
    // And the syllables sit on the spoken 4-1-3, after the filler (which ends near frame 45).
    assert!(s[0].span.start_frame >= 45, "{:?}", s[0].span);
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
            assert!(matches!(s.judgement.measured, Measured::NotMeasured { .. }));
        }
    }
    assert_eq!(r.null_llr, 0.0);
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
fn empty_candidate_set_and_empty_candidate_error() {
    let a = quiet(40);
    assert_eq!(
        decode(&a, &cmn(), &std_g(), &[]),
        Err(AssessError::Pack {
            message: "empty candidate set".into()
        })
    );
    assert_eq!(
        decode(&a, &cmn(), &std_g(), &[c("x", &["1"]), c("nil", &[])]),
        Err(AssessError::Pack {
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
    // (2-4-1 rather than 4-1-3: in this synthetic 4-1-3, pYIN leaves the initial fall with too few
    // voiced frames to measure, an upstream f0 matter this test is not about.)
    let a = analysis_of(&three(vec![vec![3., 5.], vec![5., 1.], vec![5., 5.]]));
    let r = decode(&a, &cmn(), &std_g(), &[c("spell", &["2", "4", "1"])]).unwrap();
    let s = &r.candidates[0].syllables;
    for (fit, tone) in s.iter().zip(["2", "4", "1"]) {
        assert_eq!(fit.judgement.expected.0, tone);
        assert!(fit.judgement.llr_target > 0.0, "{fit:#?}");
        assert!(matches!(fit.judgement.measured, Measured::Full));
    }
    // Each syllable lands on its spoken one (frames 20-45, 51-76, 82-107): it may absorb the
    // 6-frame pause beside it, since the duration prior centres on the inter-nucleus interval.
    let spoken = [(20, 45), (51, 76), (82, 107)];
    for (fit, (start, end)) in s.iter().zip(spoken) {
        assert!(fit.span.start_frame.abs_diff(start) <= 6, "{:?}", fit.span);
        assert!(fit.span.end_frame.abs_diff(end) <= 6, "{:?}", fit.span);
    }
    assert!(r.candidates[0].posterior > r.null_posterior);
}

#[test]
fn candidate_llr_is_the_sum_of_its_path() {
    // llr = Σ (judge's llr_target + dur) − filler_per_frame × speech frames outside syllables,
    // with dur = −(ln(d/r))²/(2σ²) and r the median inter-nucleus interval.
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

    let threshold = speech_threshold(&a.energy, &SegmentParams::default());
    let speech = |from: u32, to: u32| {
        (from..to)
            .filter(|&f| a.energy.db[f as usize] >= threshold)
            .count() as f64
    };
    let mut frames: Vec<u32> = a.nuclei.iter().map(|n| n.frame).collect();
    frames.sort_unstable();
    let mut gaps: Vec<u32> = frames.windows(2).map(|w| w[1] - w[0]).collect();
    gaps.sort_unstable();
    assert_eq!(gaps.len() % 2, 1, "{frames:?}");
    let rate_s = f64::from(gaps[gaps.len() / 2]) * 0.01;
    let sigma = f64::from(d.dur_sigma);
    let filler = f64::from(d.filler_per_frame);
    let n_frames = a.energy.db.len() as u32;

    for cand in &r.candidates {
        let mut want = 0.0;
        let mut at = 0;
        for s in &cand.syllables {
            let (from, to) = (s.span.start_frame, s.span.end_frame);
            let x = (f64::from(to - from) * 0.01 / rate_s).ln();
            want += f64::from(s.judgement.llr_target) - x * x / (2.0 * sigma * sigma);
            want -= filler * speech(at, from);
            at = to;
        }
        want -= filler * speech(at, n_frames);
        approx::assert_abs_diff_eq!(f64::from(cand.llr), want, epsilon = 1e-4);
    }
    // A lexical variant widens the target without losing the spoken 4-1-3.
    let m = r.candidates.iter().find(|x| x.id.0 == "mixed").unwrap();
    assert!(
        m.syllables.iter().all(|f| f.judgement.llr_target > 0.0),
        "{m:#?}"
    );
}
