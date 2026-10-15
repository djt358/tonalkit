//! `roll_register` (ruling R111) and `roll_register_lite` (ruling R120) through the facade:
//! synthetic speech analysed, assessed and rolled in, utterance after utterance, by a speaker who
//! starts 3 st high and settles.

use tonekit::{
    analyze, assess, roll_register, roll_register_lite, AccentId, Analysis, AnalyzeOptions,
    AssessError, AssessRequest, Candidate, CandidateId, GradingTarget, LanguagePack, MeasureIssue,
    Register, RegisterSource, RollingParams, RollingRegister, ToneId, ToneTarget,
    UtteranceAssessment,
};
use tonekit_testkit::{synth, SynthSpec, SynthSyllable};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");
const RATE: u32 = 16_000;

fn cmn() -> LanguagePack {
    LanguagePack::from_toml(CMN_TOML, Some(CMN_CALIB)).unwrap()
}

fn request(tones: &[&str]) -> AssessRequest {
    AssessRequest {
        grading: GradingTarget {
            accent: AccentId("cmn-standard".into()),
            style: None,
            style_weight: 0.0,
        },
        intended: Candidate {
            id: CandidateId("said".into()),
            targets: tones
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
    }
}

fn knots(tone: &str) -> Vec<f32> {
    match tone {
        "1" => vec![5.0, 5.0],
        "2" => vec![3.0, 5.0],
        "3" => vec![2.0, 1.0, 4.0],
        _ => vec![5.0, 1.0],
    }
}

/// `tones` spoken between `floor_hz` and `ceil_hz` (250 ms syllables); `onset_ms` of each is
/// noise (250: whispered).
fn spoken(tones: &[&str], floor_hz: f32, ceil_hz: f32, onset_ms: f32, seed: u64) -> Vec<f32> {
    synth(&SynthSpec {
        floor_hz,
        ceil_hz,
        lead_ms: 200.0,
        tail_ms: 200.0,
        syllables: tones
            .iter()
            .map(|t| SynthSyllable {
                chao: knots(t),
                dur_ms: 250.0,
                gap_after_ms: 60.0,
                unvoiced_onset_ms: onset_ms,
                creak: None,
            })
            .collect(),
        snr_db: None,
        seed,
    })
    .pcm
}

/// Grades `pcm` with `rolling`'s register (a cold start without one): its analysis and assessment.
fn grade(
    rolling: Option<&RollingRegister>,
    pcm: &[f32],
    tones: &[&str],
) -> (Analysis, UtteranceAssessment) {
    let a = analyze(
        pcm,
        RATE,
        rolling.map(|r| &r.register),
        &AnalyzeOptions::default(),
    )
    .unwrap();
    let graded = assess(&a, &cmn(), &request(tones)).unwrap();
    (a, graded)
}

/// Grades `pcm` with `rolling`'s register and rolls it in.
fn step(
    rolling: Option<&RollingRegister>,
    pcm: &[f32],
    tones: &[&str],
    params: &RollingParams,
) -> (UtteranceAssessment, RollingRegister) {
    let (a, graded) = grade(rolling, pcm, tones);
    let rolled = roll_register(rolling, &a, &graded, params).unwrap();
    (graded, rolled)
}

const PHRASES: [[&str; 3]; 4] = [
    ["1", "2", "4"],
    ["4", "1", "3"],
    ["2", "4", "1"],
    ["3", "1", "2"],
];

/// Rolls `a` into `r` (its voiced frames do not depend on the register it was given).
fn roll_in(
    r: &mut Option<RollingRegister>,
    a: &Analysis,
    graded: &UtteranceAssessment,
    p: &RollingParams,
) {
    *r = Some(roll_register(r.as_ref(), a, graded, p).unwrap());
}

#[test]
fn a_speaker_who_settles_is_followed_and_pooling_lags() {
    // The drill and 12 phrases 3 st up (119-238 Hz), then 24 phrases settled at 100-200 Hz,
    // each graded with the rolling register built from what came before.
    let up = 2f32.powf(0.25);
    let params = RollingParams {
        half_life_s: Some(5.0),
        max_share: None,
    };
    let (mut rolling, mut pooled, mut drill) = (None, None, None);
    for k in 0..4 {
        let tones = ["1", "2", "3", "4"];
        let (a, graded) = grade(
            rolling.as_ref(),
            &spoken(&tones, 100.0 * up, 200.0 * up, 0.0, k),
            &tones,
        );
        for (r, p) in [
            (&mut rolling, &params),
            (&mut pooled, &RollingParams::POOLED),
            (&mut drill, &RollingParams::POOLED),
        ] {
            roll_in(r, &a, &graded, p);
        }
    }
    let mut settled = None; // the truth: what the settled phrases alone say, pooled
    for k in 0..36 {
        let tones = PHRASES[k % 4];
        let (floor, ceil) = if k < 12 {
            (100.0 * up, 200.0 * up)
        } else {
            (100.0, 200.0)
        };
        let (a, graded) = grade(
            rolling.as_ref(),
            &spoken(&tones, floor, ceil, 0.0, 10 + k as u64),
            &tones,
        );
        assert!(graded.overall.is_some());
        roll_in(&mut rolling, &a, &graded, &params);
        roll_in(&mut pooled, &a, &graded, &RollingParams::POOLED);
        if k >= 12 {
            roll_in(&mut settled, &a, &graded, &RollingParams::POOLED);
        }
    }
    let truth = settled.unwrap().register;
    let off = |r: &Register| {
        [
            (r.floor_st - truth.floor_st).abs(),
            (r.median_st - truth.median_st).abs(),
            (r.ceil_st - truth.ceil_st).abs(),
        ]
        .into_iter()
        .fold(0.0, f32::max)
    };
    let (rolling, pooled, drill) = (
        rolling.unwrap().register,
        pooled.unwrap().register,
        drill.unwrap().register,
    );
    assert_eq!(rolling.n_syllables, 16 + 108);
    assert!(
        off(&rolling) < 0.5 * off(&pooled) && off(&pooled) > 0.5,
        "truth {truth:?} rolling {rolling:?} pooled {pooled:?}"
    );
    assert!(off(&drill) > 2.0, "truth {truth:?} drill {drill:?}");
}

#[test]
fn the_rolled_register_is_what_the_next_analysis_is_given() {
    let pcm = spoken(&["4", "1", "3"], 100.0, 200.0, 0.0, 1);
    let (graded, first) = step(None, &pcm, &["4", "1", "3"], &RollingParams::DEFAULT);
    assert_eq!(first.register.n_syllables, 3);
    // A cold start's register_update is unchanged by rolling (it is still the cold register).
    assert_eq!(graded.register_update.n_syllables, 3);
    let a = analyze(
        &pcm,
        RATE,
        Some(&first.register),
        &AnalyzeOptions::default(),
    )
    .unwrap();
    assert_eq!(a.register_source, RegisterSource::Given);
    assert!(a.issues.contains(&MeasureIssue::ColdStartRegister)); // 3 of 30 syllables
}

#[test]
fn a_whispered_utterance_teaches_nothing() {
    let pcm = spoken(&["4", "1", "3"], 100.0, 200.0, 0.0, 2);
    let (_, before) = step(None, &pcm, &["4", "1", "3"], &RollingParams::DEFAULT);
    let whisper = spoken(&["4", "1", "3"], 100.0, 200.0, 250.0, 3);
    let (_, after) = step(
        Some(&before),
        &whisper,
        &["4", "1", "3"],
        &RollingParams::DEFAULT,
    );
    assert_eq!(after, before);
}

#[test]
fn unusable_parameters_are_an_invalid_request() {
    let pcm = spoken(&["1"], 100.0, 200.0, 0.0, 4);
    let a = analyze(&pcm, RATE, None, &AnalyzeOptions::default()).unwrap();
    let graded = assess(&a, &cmn(), &request(&["1"])).unwrap();
    for params in [
        RollingParams {
            half_life_s: Some(f32::NAN),
            max_share: None,
        },
        RollingParams {
            half_life_s: Some(-1.0),
            max_share: None,
        },
        RollingParams {
            half_life_s: Some(30.0),
            max_share: Some(1.5),
        },
        RollingParams {
            half_life_s: None,
            max_share: Some(0.03),
        },
    ] {
        let r = roll_register(None, &a, &graded, &params);
        assert!(
            matches!(r, Err(AssessError::InvalidRequest { ref message }) if message.contains("rolling register")),
            "{params:?}: {r:?}"
        );
        let r = roll_register_lite(None, &a, &graded, &params);
        assert!(
            matches!(r, Err(AssessError::InvalidRequest { ref message }) if message.contains("rolling register")),
            "{params:?}: {r:?}"
        );
    }
}

#[test]
fn the_pack_carries_the_default_parameters() {
    assert_eq!(cmn().calibration().rolling_register, RollingParams::DEFAULT);
}

// ---- the lite register (ruling R120) ------------------------------------------------------------

/// The drill and 12 phrases 3 st up, then 24 settled phrases, each graded with the lite register
/// rolled from what came before. Returns the lite register at the end, today's merge (the lite
/// register without decay) at the end, the register after the drill alone, and the truth (the
/// settled phrases' frames, pooled).
fn settle_lite(params: &RollingParams) -> (Register, Register, Register, Register) {
    let up = 2f32.powf(0.25);
    let (mut lite, mut merged, mut settled) = (None, None, None);
    for k in 0..4 {
        let tones = ["1", "2", "3", "4"];
        let pcm = spoken(&tones, 100.0 * up, 200.0 * up, 0.0, k);
        let a = analyze(&pcm, RATE, lite.as_ref(), &AnalyzeOptions::default()).unwrap();
        let graded = assess(&a, &cmn(), &request(&tones)).unwrap();
        lite = Some(roll_register_lite(lite.as_ref(), &a, &graded, params).unwrap());
        let m = roll_register_lite(merged.as_ref(), &a, &graded, &RollingParams::POOLED);
        merged = Some(m.unwrap());
    }
    let drill = merged.clone().unwrap();
    for k in 0..36 {
        let tones = PHRASES[k % 4];
        let (floor, ceil) = if k < 12 {
            (100.0 * up, 200.0 * up)
        } else {
            (100.0, 200.0)
        };
        let pcm = spoken(&tones, floor, ceil, 0.0, 10 + k as u64);
        let a = analyze(&pcm, RATE, lite.as_ref(), &AnalyzeOptions::default()).unwrap();
        let graded = assess(&a, &cmn(), &request(&tones)).unwrap();
        assert!(graded.overall.is_some());
        lite = Some(roll_register_lite(lite.as_ref(), &a, &graded, params).unwrap());
        let m = roll_register_lite(merged.as_ref(), &a, &graded, &RollingParams::POOLED);
        merged = Some(m.unwrap());
        if k >= 12 {
            roll_in(&mut settled, &a, &graded, &RollingParams::POOLED);
        }
    }
    (
        lite.unwrap(),
        merged.unwrap(),
        drill,
        settled.unwrap().register,
    )
}

/// The largest of the floor, median and ceiling errors of `r` against `truth`.
fn off(r: &Register, truth: &Register) -> f32 {
    [
        (r.floor_st - truth.floor_st).abs(),
        (r.median_st - truth.median_st).abs(),
        (r.ceil_st - truth.ceil_st).abs(),
    ]
    .into_iter()
    .fold(0.0, f32::max)
}

#[test]
fn the_lite_register_follows_a_speaker_who_settles_and_todays_merge_lags() {
    let params = RollingParams {
        half_life_s: Some(5.0),
        max_share: None,
    };
    let (lite, merged, drill, truth) = settle_lite(&params);
    assert_eq!(lite.n_syllables, 16 + 108);
    assert!(
        off(&lite, &truth) < 0.5 * off(&merged, &truth) && off(&merged, &truth) > 0.5,
        "truth {truth:?} lite {lite:?} merged {merged:?}"
    );
    assert!(off(&drill, &truth) > 2.0, "truth {truth:?} drill {drill:?}");
}

#[test]
fn without_decay_the_lite_register_is_register_update() {
    // With no decay and no cap, rolling the lite register is exactly what `assess` reports as
    // `register_update`, from a cold start on (ruling R120).
    let mut lite: Option<Register> = None;
    for k in 0..6 {
        let tones = PHRASES[k % 4];
        let pcm = spoken(&tones, 100.0, 200.0, 0.0, 20 + k as u64);
        let a = analyze(&pcm, RATE, lite.as_ref(), &AnalyzeOptions::default()).unwrap();
        let graded = assess(&a, &cmn(), &request(&tones)).unwrap();
        let rolled = roll_register_lite(lite.as_ref(), &a, &graded, &RollingParams::POOLED);
        assert_eq!(
            rolled.as_ref(),
            Ok(&graded.register_update),
            "utterance {k}"
        );
        lite = rolled.ok();
    }
}

#[test]
fn the_lite_register_learns_nothing_from_a_whisper_and_restarts_from_a_corrupt_one() {
    let pcm = spoken(&["4", "1", "3"], 100.0, 200.0, 0.0, 2);
    let a = analyze(&pcm, RATE, None, &AnalyzeOptions::default()).unwrap();
    let graded = assess(&a, &cmn(), &request(&["4", "1", "3"])).unwrap();
    let p = RollingParams::DEFAULT;
    let first = roll_register_lite(None, &a, &graded, &p).unwrap();
    assert_eq!(first.n_syllables, 3);
    let whisper = spoken(&["4", "1", "3"], 100.0, 200.0, 250.0, 3);
    let w = analyze(&whisper, RATE, Some(&first), &AnalyzeOptions::default()).unwrap();
    let hushed = assess(&w, &cmn(), &request(&["4", "1", "3"])).unwrap();
    assert_eq!(
        roll_register_lite(Some(&first), &w, &hushed, &p),
        Ok(first.clone())
    );
    // A stored register that cannot be graded against is started afresh, as `analyze` does.
    let corrupt = Register {
        median_st: f32::NAN,
        ..first.clone()
    };
    assert_eq!(
        roll_register_lite(Some(&corrupt), &a, &graded, &p),
        Ok(first)
    );
}

#[test]
fn a_lite_register_is_the_four_number_register_json() {
    let pcm = spoken(&["2", "4"], 100.0, 200.0, 0.0, 5);
    let a = analyze(&pcm, RATE, None, &AnalyzeOptions::default()).unwrap();
    let graded = assess(&a, &cmn(), &request(&["2", "4"])).unwrap();
    let lite = roll_register_lite(None, &a, &graded, &RollingParams::DEFAULT).unwrap();
    let json = serde_json::to_value(&lite).unwrap();
    let keys: Vec<&str> = json
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    assert_eq!(keys, ["ceil_st", "floor_st", "median_st", "n_syllables"]);
    let back: Register = serde_json::from_value(json).unwrap();
    assert_eq!(back, lite);
}
