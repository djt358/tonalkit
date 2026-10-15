//! The calibration's optional `rolling_register` section (ruling R111): the pack's parameters for
//! `tonekit::roll_register`.

use tonekit_core::RollingParams;
use tonekit_pack::{LanguagePack, PackError};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");

/// The shipped calibration with `section` (a JSON object's text) as its `rolling_register`.
fn with_section(section: &str) -> String {
    let end = CMN_CALIB.rfind('}').expect("a JSON object");
    format!(
        "{},\n  \"rolling_register\": {section}\n}}",
        CMN_CALIB[..end].trim_end()
    )
}

fn load(json: &str) -> Result<LanguagePack, PackError> {
    LanguagePack::from_toml(CMN_TOML, Some(json))
}

#[test]
fn without_the_section_the_default_applies() {
    let p = LanguagePack::from_toml(CMN_TOML, Some(CMN_CALIB)).unwrap();
    assert_eq!(p.calibration().rolling_register, RollingParams::DEFAULT);
    let seed = LanguagePack::from_toml(CMN_TOML, None).unwrap();
    assert_eq!(seed.calibration().rolling_register, RollingParams::DEFAULT);
    assert_eq!(RollingParams::default(), RollingParams::DEFAULT);
}

#[test]
fn the_section_sets_the_pack_parameters() {
    let p = load(&with_section(r#"{"half_life_s": 12.5, "max_share": 0.02}"#)).unwrap();
    assert_eq!(
        p.calibration().rolling_register,
        RollingParams {
            half_life_s: Some(12.5),
            max_share: Some(0.02)
        }
    );
    // Both null: plain pooling (ruling R107).
    let p = load(&with_section(r#"{"half_life_s": null, "max_share": null}"#)).unwrap();
    assert_eq!(p.calibration().rolling_register, RollingParams::POOLED);
    // Decay without a cap.
    let p = load(&with_section(r#"{"half_life_s": 40.0, "max_share": null}"#)).unwrap();
    assert_eq!(p.calibration().rolling_register.max_share, None);
}

#[test]
fn a_missing_misspelt_or_extra_field_is_a_parse_error() {
    // A forgotten half-life must not silently turn decay off.
    for section in [
        r#"{"max_share": 0.03}"#,
        r#"{"half_life_s": 30.0}"#,
        r#"{"half_life": 30.0, "max_share": 0.03}"#,
        r#"{"half_life_s": 30.0, "max_share": 0.03, "extra": 1}"#,
        r#"{"half_life_s": "30", "max_share": 0.03}"#,
    ] {
        let r = load(&with_section(section));
        assert!(matches!(r, Err(PackError::Parse(_))), "{section}: {r:?}");
    }
}

#[test]
fn unusable_values_are_invalid() {
    for (section, says) in [
        (r#"{"half_life_s": 0.0, "max_share": 0.03}"#, "half_life_s"),
        (r#"{"half_life_s": -5.0, "max_share": 0.03}"#, "half_life_s"),
        (r#"{"half_life_s": 30.0, "max_share": 0.0}"#, "max_share"),
        (r#"{"half_life_s": 30.0, "max_share": 1.0}"#, "max_share"),
        (
            r#"{"half_life_s": null, "max_share": 0.03}"#,
            "needs a half_life_s",
        ),
    ] {
        let r = load(&with_section(section));
        assert!(
            matches!(r, Err(PackError::Invalid(ref m))
                if m.contains("rolling_register") && m.contains(says)),
            "{section}: {r:?}"
        );
    }
}
