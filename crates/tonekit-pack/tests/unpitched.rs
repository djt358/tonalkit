//! Ruling R103: the calibration's evidence for unpitched syllables, and how a syllable is judged on
//! it.

use tonekit_core::{MeasureIssue, Measured, ToneId, ToneTarget, WeightedTone};
use tonekit_pack::{LanguagePack, PackError, TargetContext};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");

/// The shipped calibration with `unpitched` set to `section` (JSON text).
fn calib_with(section: &str) -> String {
    let mut calib: serde_json::Value = serde_json::from_str(CMN_CALIB).unwrap();
    calib["unpitched"] = serde_json::from_str(section).unwrap();
    calib.to_string()
}

const TABLE: &str = r#"{
    "phrase_final": { "1": -5.0, "2": -3.5, "3": -0.5, "4": -2.0, "5": -3.0 },
    "other": { "1": -5.0, "2": -4.0, "3": -1.5, "4": -3.0, "5": -3.0 }
}"#;

fn pack() -> LanguagePack {
    LanguagePack::from_toml(CMN_TOML, Some(&calib_with(TABLE))).unwrap()
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
        index: 2,
        count: 3,
        prev: Some(ToneId("1".into())),
        phrase_final,
    }
}

#[test]
fn an_unpitched_syllable_is_evidence_for_the_tones_that_creak() {
    let p = pack();
    let three = p
        .judge_unpitched(&target("3"), &ctx(true), &[])
        .unwrap()
        .unwrap();
    let one = p
        .judge_unpitched(&target("1"), &ctx(true), &[])
        .unwrap()
        .unwrap();
    assert!(three.llr_target > 0.5, "{three:?}");
    assert!(one.llr_target < -2.5, "{one:?}");
    // The background is the prior-weighted mixture of every tone.
    let prior = p.prior();
    let ll = [-5.0f64, -3.5, -0.5, -2.0, -3.0];
    let background = prior
        .iter()
        .zip(ll)
        .map(|(p, l)| f64::from(*p) * l.exp())
        .sum::<f64>()
        .ln();
    assert!((f64::from(three.llr_target) - (-0.5 - background)).abs() < 1e-5);
    assert_eq!(three.loglik, vec![-5.0, -3.5, -0.5, -2.0, -3.0]);
    assert_eq!(three.heard, Some(ToneId("3".into())));
    assert!(three.distance.is_none() && three.component.is_none() && three.deltas.is_empty());
    assert_eq!(
        three.measured,
        Measured::Partial {
            issues: vec![MeasureIssue::Unpitched]
        }
    );
    // Elsewhere in the phrase the other table is read, and tone 3 is no longer heard.
    let mid = p
        .judge_unpitched(&target("3"), &ctx(false), &[])
        .unwrap()
        .unwrap();
    assert_eq!(mid.loglik[2], -1.5);
    assert!(mid.llr_target < three.llr_target);
}

#[test]
fn analysis_issues_are_carried_after_unpitched() {
    let p = pack();
    let j = p
        .judge_unpitched(&target("3"), &ctx(true), &[MeasureIssue::LowSnr])
        .unwrap()
        .unwrap();
    assert_eq!(
        j.measured,
        Measured::Partial {
            issues: vec![MeasureIssue::Unpitched, MeasureIssue::LowSnr]
        }
    );
}

#[test]
fn lexical_variants_mix_by_weight() {
    let p = pack();
    let mut t = target("1");
    t.lexical_variants.push(WeightedTone {
        tone: ToneId("3".into()),
        weight: 0.5,
    });
    let mixed = p.judge_unpitched(&t, &ctx(true), &[]).unwrap().unwrap();
    let three = p
        .judge_unpitched(&target("3"), &ctx(true), &[])
        .unwrap()
        .unwrap();
    let one = p
        .judge_unpitched(&target("1"), &ctx(true), &[])
        .unwrap()
        .unwrap();
    assert!(one.llr_target < mixed.llr_target && mixed.llr_target < three.llr_target);
    t.lexical_variants[0].weight = 1.5;
    assert!(matches!(
        p.judge_unpitched(&t, &ctx(true), &[]),
        Err(PackError::Invalid(_))
    ));
}

#[test]
fn without_evidence_there_is_no_judgement() {
    let mut calib: serde_json::Value = serde_json::from_str(CMN_CALIB).unwrap();
    calib.as_object_mut().unwrap().remove("unpitched");
    let p = LanguagePack::from_toml(CMN_TOML, Some(&calib.to_string())).unwrap();
    assert!(p.calibration().unpitched.is_none());
    assert_eq!(p.judge_unpitched(&target("3"), &ctx(true), &[]), Ok(None));
}

#[test]
fn the_evidence_must_name_every_tone_as_a_log_probability() {
    let bad = [
        // A tone missing, or one the pack does not have.
        TABLE.replace(r#", "5": -3.0 },"#, " },"),
        TABLE.replace(r#""5": -3.0 },"#, r#""5": -3.0, "6": -1.0 },"#),
        // Not a log-probability.
        TABLE.replace(r#""3": -0.5"#, r#""3": 0.2"#),
    ];
    for section in bad {
        let r = LanguagePack::from_toml(CMN_TOML, Some(&calib_with(&section)));
        assert!(matches!(r, Err(PackError::Invalid(_))), "{section}: {r:?}");
    }
    // A section with an unknown key is a parse error.
    let r = LanguagePack::from_toml(
        CMN_TOML,
        Some(&calib_with(
            r#"{ "phrase_final": {}, "other": {}, "extra": {} }"#,
        )),
    );
    assert!(matches!(r, Err(PackError::Parse(_))), "{r:?}");
}
