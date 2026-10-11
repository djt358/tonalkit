//! Ruling R108: the calibration's evidence for creaky tails, added to every tone's likelihood of a
//! shape flagged `CreakyTail`.

use tonekit_core::{
    GradingTarget, MeasureIssue, Measured, TbuSpan, ToneId, ToneShape, ToneTarget, WeightedTone,
};
use tonekit_pack::{LanguagePack, PackError, TargetContext};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");

const TABLE: &str = r#"{
    "phrase_final": { "1": -4.0, "2": -1.5, "3": -0.7, "4": -0.2, "5": -2.0 },
    "other": { "1": -4.0, "2": -2.0, "3": -1.0, "4": -1.2, "5": -2.0 }
}"#;

/// The shipped calibration with `creaky_tail` set to `section` (JSON text), or removed.
fn calib_with(section: Option<&str>) -> String {
    let mut calib: serde_json::Value = serde_json::from_str(CMN_CALIB).unwrap();
    let map = calib.as_object_mut().unwrap();
    match section {
        Some(s) => map.insert("creaky_tail".into(), serde_json::from_str(s).unwrap()),
        None => map.remove("creaky_tail"),
    };
    calib.to_string()
}

fn pack(section: Option<&str>) -> LanguagePack {
    LanguagePack::from_toml(CMN_TOML, Some(&calib_with(section))).unwrap()
}

fn g() -> GradingTarget {
    GradingTarget {
        accent: tonekit_core::AccentId("cmn-standard".into()),
        style: None,
        style_weight: 0.0,
    }
}

fn target(tone: &str) -> ToneTarget {
    ToneTarget {
        tone: ToneId(tone.into()),
        lexical_variants: Vec::new(),
        label: None,
    }
}

fn ctx(phrase_final: bool) -> TargetContext {
    TargetContext {
        index: 1,
        count: 2,
        prev: Some(ToneId("1".into())),
        phrase_final,
    }
}

/// A level contour at Chao 4.2: what a high voice's phrase-final tone 4 can measure as when its
/// fall goes creaky and loses its pitch.
fn level_high() -> ToneShape {
    let contour = vec![4.2f32; 10];
    ToneShape {
        span: TbuSpan {
            start_frame: 0,
            end_frame: 15,
        },
        onset: 4.2,
        offset: 4.2,
        mean: 4.2,
        slope: 0.0,
        curvature: 0.0,
        turning_point: None,
        range: 0.0,
        duration_ms: 150.0,
        voiced_fraction: 1.0,
        f0_confidence: 1.0,
        phonation: None,
        voiced_weights: vec![1.0; 10],
        contour,
    }
}

const TAIL: &[MeasureIssue] = &[MeasureIssue::CreakyTail];

#[test]
fn a_creaky_tail_adds_its_log_probability_to_every_tone() {
    let with = pack(Some(TABLE));
    let without = pack(None);
    let x = level_high();
    let plain = without
        .judge(&g(), &x, &target("4"), &ctx(true), TAIL)
        .unwrap();
    let tailed = with
        .judge(&g(), &x, &target("4"), &ctx(true), TAIL)
        .unwrap();
    let table = [-4.0f32, -1.5, -0.7, -0.2, -2.0];
    for ((a, b), t) in tailed.loglik.iter().zip(&plain.loglik).zip(table) {
        assert!((a - (b + t)).abs() < 1e-4, "{a} vs {b} + {t}");
    }
    // tone_loglik and judge agree bit for bit.
    for (i, tone) in with.inventory().iter().enumerate() {
        let ll = with.tone_loglik(&g(), &x, tone, &ctx(true), TAIL).unwrap();
        assert_eq!(ll.to_bits(), tailed.loglik[i].to_bits(), "{tone:?}");
    }
    // The level-high shape is likelier a tone 1 than a tone 4; the tail moves 3.8 nats of
    // evidence from tone 1 to tone 4, and the target's LLR up.
    assert!(plain.loglik[0] > plain.loglik[3], "{plain:?}");
    let gap = |j: &tonekit_core::ToneJudgement| j.loglik[3] - j.loglik[0];
    assert!((gap(&tailed) - gap(&plain) - 3.8).abs() < 1e-4);
    assert!(tailed.llr_target > plain.llr_target + 1.0, "{tailed:?}");
    let one = with
        .judge(&g(), &x, &target("1"), &ctx(true), TAIL)
        .unwrap();
    let plain_one = without
        .judge(&g(), &x, &target("1"), &ctx(true), TAIL)
        .unwrap();
    assert!(one.llr_target < plain_one.llr_target - 1.0, "{one:?}");
    assert_eq!(
        tailed.measured,
        Measured::Partial {
            issues: vec![MeasureIssue::CreakyTail]
        }
    );
}

#[test]
fn the_place_picks_the_table() {
    let p = pack(Some(TABLE));
    let x = level_high();
    let final_ = p.judge(&g(), &x, &target("4"), &ctx(true), TAIL).unwrap();
    let medial = p.judge(&g(), &x, &target("4"), &ctx(false), TAIL).unwrap();
    let base = pack(None);
    let b_final = base
        .judge(&g(), &x, &target("4"), &ctx(true), TAIL)
        .unwrap();
    let b_medial = base
        .judge(&g(), &x, &target("4"), &ctx(false), TAIL)
        .unwrap();
    assert!((final_.loglik[3] - b_final.loglik[3] - -0.2).abs() < 1e-4);
    assert!((medial.loglik[3] - b_medial.loglik[3] - -1.2).abs() < 1e-4);
}

#[test]
fn no_tail_or_no_evidence_changes_nothing() {
    let x = level_high();
    let with = pack(Some(TABLE));
    let without = pack(None);
    // A shape with no tail is scored as without the evidence, bit for bit.
    let a = with.judge(&g(), &x, &target("4"), &ctx(true), &[]).unwrap();
    let b = without
        .judge(&g(), &x, &target("4"), &ctx(true), &[])
        .unwrap();
    assert_eq!(a, b);
    // A tail with no evidence in the calibration says nothing about the tone.
    let c = without
        .judge(&g(), &x, &target("4"), &ctx(true), TAIL)
        .unwrap();
    assert_eq!(c.loglik, b.loglik);
    assert_eq!(c.llr_target, b.llr_target);
}

#[test]
fn lexical_variants_mix_the_tail_by_weight() {
    let p = pack(Some(TABLE));
    let x = level_high();
    let mut t = target("1");
    t.lexical_variants.push(WeightedTone {
        tone: ToneId("4".into()),
        weight: 0.5,
    });
    let mixed = p.judge(&g(), &x, &t, &ctx(true), TAIL).unwrap();
    let base = pack(None).judge(&g(), &x, &t, &ctx(true), TAIL).unwrap();
    // The target gains ln(0.5·e^-4 + 0.5·e^-0.2) over the shape alone; the background gains the
    // prior-weighted tail of every tone.
    let gain = (0.5f64 * (-4.0f64).exp() + 0.5 * (-0.2f64).exp()).ln();
    let prior = p.prior();
    let shift = |j: &tonekit_core::ToneJudgement, tails: &[f64]| {
        prior
            .iter()
            .zip(&j.loglik)
            .zip(tails)
            .map(|((p, l), t)| f64::from(*p) * (f64::from(*l) + t).exp())
            .sum::<f64>()
            .ln()
    };
    let bg_with = shift(&base, &[-4.0, -1.5, -0.7, -0.2, -2.0]);
    let bg_without = shift(&base, &[0.0; 5]);
    let want = f64::from(base.llr_target) + gain - (bg_with - bg_without);
    assert!(
        (f64::from(mixed.llr_target) - want).abs() < 1e-3,
        "{mixed:?}"
    );
}

#[test]
fn the_evidence_must_name_every_tone_as_a_log_probability() {
    let bad = [
        TABLE.replace(r#", "5": -2.0 },"#, " },"),
        TABLE.replace(r#""4": -0.2"#, r#""4": 0.1"#),
    ];
    for section in bad {
        let r = LanguagePack::from_toml(CMN_TOML, Some(&calib_with(Some(&section))));
        assert!(matches!(r, Err(PackError::Invalid(_))), "{section}: {r:?}");
    }
}
