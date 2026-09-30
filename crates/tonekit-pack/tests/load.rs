//! Loading and validation of language packs (spec §6.2).

use tonekit_core::{AccentId, FusionWeights, ToneId};
use tonekit_pack::{Calibration, DecodeParams, LanguagePack, PackError};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");
const CMN_PROVENANCE: &str = include_str!("../../../packs/cmn/PROVENANCE.toml");

fn cmn() -> LanguagePack {
    LanguagePack::from_toml(CMN_TOML, Some(CMN_CALIB)).unwrap()
}

fn tone(s: &str) -> ToneId {
    ToneId(s.into())
}

/// Replace `from` with `to`, panicking if `from` is absent so a stale mutation cannot pass silently.
fn mutate(src: &str, from: &str, to: &str) -> String {
    assert!(src.contains(from), "mutation target not found: {from:?}");
    src.replacen(from, to, 1)
}

fn load_err(toml: &str) -> PackError {
    LanguagePack::from_toml(toml, None).expect_err("pack must be rejected")
}

fn assert_invalid(toml: &str) {
    match load_err(toml) {
        PackError::Invalid(_) => {}
        other => panic!("expected Invalid, got {other:?}"),
    }
}

/// A two-tone pack with a caller-supplied accent section appended.
fn mini(accents: &str) -> String {
    format!(
        r#"
[pack]
lect = "tst"
version = "0.0.1"
tbu = "syllable"
capabilities = ["register"]
base_accent = "a"
heard_threshold = 0.6
prior = {{ "1" = 0.5, "2" = 0.5 }}

[[tone]]
id = "1"
name = "high"
chao = [5, 5]

[[tone]]
id = "2"
name = "rise"
chao = [3, 5]

[tolerance]
contour = 0.7
onset = 0.8
offset = 0.8
turning_point = 0.2

{accents}
"#
    )
}

const ONE_ACCENT: &str = r#"
[[accent]]
id = "a"
name = "A"
"#;

#[test]
fn loads_cmn_with_five_tones_and_two_accents() {
    let p = cmn();
    assert_eq!(p.inventory().len(), 5);
    assert!(p.has_accent(&AccentId("cmn-TW".into())));
    approx::assert_abs_diff_eq!(p.prior().iter().sum::<f32>(), 1.0, epsilon = 1e-3);
}

#[test]
fn cmn_metadata_and_accessors() {
    let p = cmn();
    assert_eq!(p.lect().0, "cmn");
    assert_eq!(p.version(), "0.3.0");
    assert_eq!(p.base_accent(), &AccentId("cmn-standard".into()));
    assert!(p.has_accent(&AccentId("cmn-standard".into())));
    assert!(!p.has_accent(&AccentId("cmn-XX".into())));
    approx::assert_abs_diff_eq!(p.heard_threshold(), 0.6, epsilon = 1e-6);
    // Inventory order is [[tone]] file order; prior is aligned with it.
    let ids: Vec<&str> = p.inventory().iter().map(|t| t.0.as_str()).collect();
    assert_eq!(ids, ["1", "2", "3", "4", "5"]);
    let expected = [0.22, 0.22, 0.16, 0.30, 0.10];
    for (got, want) in p.prior().iter().zip(expected) {
        approx::assert_abs_diff_eq!(*got, want, epsilon = 1e-6);
    }
    assert_eq!(p.confusions().len(), 3);
    assert_eq!(p.confusions()[0], (tone("2"), tone("3")));
}

#[test]
fn unvoiced_ok_region_is_per_tone() {
    let p = cmn();
    assert_eq!(p.unvoiced_ok(&tone("3")), Some((0.3, 0.8)));
    assert_eq!(p.unvoiced_ok(&tone("1")), None);
    assert_eq!(p.unvoiced_ok(&tone("nope")), None);
}

fn seed_calibration() -> Calibration {
    Calibration {
        temperature: 1.0,
        fusion: FusionWeights {
            beta0: 0.0,
            beta_acoustic: 1.0,
            beta_transcript: 0.5,
            beta_neural: 0.0,
            veto_cap: 0.05,
        },
        decode: DecodeParams {
            filler_per_frame: 0.03,
            unvoiced_syllable_llr: -3.0,
            insertion_llr: -2.0,
            null_bias: -2.0,
            dur_sigma: 0.4,
            default_rate_s: 0.22,
        },
    }
}

#[test]
fn default_calibration_is_the_seed_and_matches_the_shipped_file() {
    let none = LanguagePack::from_toml(CMN_TOML, None).unwrap();
    assert_eq!(none.calibration(), &seed_calibration());
    assert_eq!(cmn().calibration(), &seed_calibration());
    assert_eq!(Calibration::default(), seed_calibration());
}

#[test]
fn calibration_json_overrides_the_seed() {
    let json = mutate(CMN_CALIB, "\"temperature\": 1.0", "\"temperature\": 2.5");
    let p = LanguagePack::from_toml(CMN_TOML, Some(&json)).unwrap();
    assert_eq!(p.calibration().temperature, 2.5);
    assert_eq!(p.calibration().decode, seed_calibration().decode);
}

#[test]
fn rejects_bad_calibration() {
    for (from, to) in [
        ("\"temperature\": 1.0", "\"temperature\": 0.0"),
        ("\"temperature\": 1.0", "\"temperature\": -1.0"),
        ("\"dur_sigma\": 0.4", "\"dur_sigma\": 0.0"),
        ("\"default_rate_s\": 0.22", "\"default_rate_s\": -0.1"),
        ("\"veto_cap\": 0.05", "\"veto_cap\": 1.5"),
        ("\"filler_per_frame\": 0.03", "\"filler_per_frame\": -0.03"),
    ] {
        let json = mutate(CMN_CALIB, from, to);
        let r = LanguagePack::from_toml(CMN_TOML, Some(&json));
        assert!(matches!(r, Err(PackError::Invalid(_))), "{to}: {r:?}");
    }
    // Not JSON, unknown field, missing field: all Parse errors.
    for json in [
        "not json".to_string(),
        mutate(CMN_CALIB, "\"temperature\"", "\"temp\""),
        mutate(
            CMN_CALIB,
            "\"veto_cap\": 0.05",
            "\"veto_cap\": 0.05, \"extra\": 1",
        ),
    ] {
        let r = LanguagePack::from_toml(CMN_TOML, Some(&json));
        assert!(matches!(r, Err(PackError::Parse(_))), "{json}: {r:?}");
    }
}

#[test]
fn insertion_llr_is_a_required_calibration_field() {
    // R33: the per-nucleus insertion cost is read from the file, and a file without it is invalid.
    let json = mutate(
        CMN_CALIB,
        "\"insertion_llr\": -2.0",
        "\"insertion_llr\": -4.5",
    );
    let p = LanguagePack::from_toml(CMN_TOML, Some(&json)).unwrap();
    assert_eq!(p.calibration().decode.insertion_llr, -4.5);
    let json = mutate(CMN_CALIB, "\"insertion_llr\": -2.0,", "");
    let r = LanguagePack::from_toml(CMN_TOML, Some(&json));
    assert!(
        matches!(r, Err(PackError::Parse(ref m)) if m.contains("insertion_llr")),
        "{r:?}"
    );
}

/// Load the cmn pack with the decode field `field` changed from its seed value to `value`.
fn load_with_decode_llr(field: &str, seed: &str, value: &str) -> Result<LanguagePack, PackError> {
    let json = mutate(
        CMN_CALIB,
        &format!("\"{field}\": {seed}"),
        &format!("\"{field}\": {value}"),
    );
    LanguagePack::from_toml(CMN_TOML, Some(&json))
}

#[test]
fn unvoiced_syllable_llr_must_not_be_positive() {
    // A positive value would reward skipped or unmeasurable syllables.
    let r = load_with_decode_llr("unvoiced_syllable_llr", "-3.0", "0.5");
    assert!(
        matches!(r, Err(PackError::Invalid(ref m))
            if m.contains("decode.unvoiced_syllable_llr must be <= 0") && m.contains("0.5")),
        "{r:?}"
    );
    // Zero (a free skip) and the seed both load.
    for ok in ["0.0", "-3.0"] {
        let p = load_with_decode_llr("unvoiced_syllable_llr", "-3.0", ok).unwrap();
        assert_eq!(
            p.calibration().decode.unvoiced_syllable_llr,
            ok.parse::<f32>().unwrap()
        );
    }
}

#[test]
fn insertion_llr_must_not_be_positive() {
    // A positive value would reward skipped or unmeasurable syllables.
    let r = load_with_decode_llr("insertion_llr", "-2.0", "0.5");
    assert!(
        matches!(r, Err(PackError::Invalid(ref m))
            if m.contains("decode.insertion_llr must be <= 0") && m.contains("0.5")),
        "{r:?}"
    );
    for ok in ["0.0", "-2.0"] {
        let p = load_with_decode_llr("insertion_llr", "-2.0", ok).unwrap();
        assert_eq!(
            p.calibration().decode.insertion_llr,
            ok.parse::<f32>().unwrap()
        );
    }
}

#[test]
fn provenance_declares_the_pack_and_its_calib_file_and_no_sources() {
    let v: toml::Table = toml::from_str(CMN_PROVENANCE).unwrap();
    // Every data file of the pack is attested (`tkh provenance` checks the list is complete).
    let artifacts: Vec<&str> = v["artifacts"]
        .as_array()
        .unwrap()
        .iter()
        .map(|a| a.as_str().unwrap())
        .collect();
    assert_eq!(
        artifacts,
        ["packs/cmn/cmn.toml", "packs/cmn/cmn.calib.json"]
    );
    assert!(v["note"].as_str().unwrap().contains("not fitted"));
    assert!(
        v.get("source").is_none(),
        "seed pack must list zero sources"
    );
}

#[test]
fn rejects_unresolvable_context() {
    // Tone "5" is "context"; drop the fallback so that prev = None (and prev = "2".."4"
    // after the t5-after-* rules are unreachable) has no matching rule.
    let toml = mutate(
        CMN_TOML,
        "label = \"t5-default\"\nwhen = { tone = \"5\" }",
        "label = \"t5-default\"\nwhen = { tone = \"5\", prev = \"1\" }",
    );
    match load_err(&toml) {
        PackError::MissingRealization { tone, context } => {
            assert_eq!(tone, ToneId("5".into()));
            assert!(context.contains("cmn-standard"), "{context}");
        }
        other => panic!("expected MissingRealization, got {other:?}"),
    }
}

#[test]
fn context_tone_without_any_rule_is_missing_realization() {
    // The only accent has a rule for tone "1" but none for tone "2".
    let toml = mini(
        r#"
[[accent]]
id = "a"
name = "A"
[[accent.realize]]
label = "ok"
when = { tone = "1" }
chao = [5]
"#,
    );
    // Both tones have literal citations here, so this loads.
    LanguagePack::from_toml(&toml, None).unwrap();
    let ctx_tone = mutate(&toml, "chao = [3, 5]", "chao = \"context\"");
    match load_err(&ctx_tone) {
        PackError::MissingRealization { tone, .. } => assert_eq!(tone, ToneId("2".into())),
        other => panic!("expected MissingRealization, got {other:?}"),
    }
}

#[test]
fn rejects_unknown_capability_and_bad_weights() {
    let caps = mutate(
        CMN_TOML,
        "capabilities = [\"register\"]",
        "capabilities = [\"phonation\"]",
    );
    assert_invalid(&caps);

    let weights = mutate(
        CMN_TOML,
        "weight = 0.6 }, { chao = [2, 1], weight = 0.4 }",
        "weight = 0.5 }, { chao = [2, 1], weight = 0.3 }",
    );
    assert_invalid(&weights);
}

#[test]
fn rejects_negative_or_zero_mixture_weights() {
    let neg = mutate(
        CMN_TOML,
        "weight = 0.6 }, { chao = [2, 1], weight = 0.4 }",
        "weight = 1.4 }, { chao = [2, 1], weight = -0.4 }",
    );
    assert_invalid(&neg);
    let zero = mutate(
        CMN_TOML,
        "weight = 0.6 }, { chao = [2, 1], weight = 0.4 }",
        "weight = 1.0 }, { chao = [2, 1], weight = 0.0 }",
    );
    assert_invalid(&zero);
}

#[test]
fn rejects_wrong_tbu() {
    assert_invalid(&mutate(CMN_TOML, "tbu = \"syllable\"", "tbu = \"mora\""));
}

#[test]
fn malformed_toml_and_unknown_fields_are_parse_errors() {
    assert!(matches!(load_err("[pack"), PackError::Parse(_)));
    assert!(matches!(load_err(""), PackError::Parse(_)));
    // A typo in a `when` key must not be silently ignored.
    let typo = mutate(CMN_TOML, "phrase_final = false", "phrase_finel = false");
    assert!(matches!(load_err(&typo), PackError::Parse(_)));
    let typo = mutate(CMN_TOML, "heard_threshold", "heard_thresh");
    assert!(matches!(load_err(&typo), PackError::Parse(_)));
}

#[test]
fn prior_must_match_inventory_and_be_normalisable() {
    // Sum 1.005: within 0.01, so accepted and normalised to exactly 1.
    let near = mutate(CMN_TOML, "\"5\" = 0.10", "\"5\" = 0.105");
    let p = LanguagePack::from_toml(&near, None).unwrap();
    approx::assert_abs_diff_eq!(p.prior().iter().sum::<f32>(), 1.0, epsilon = 1e-6);
    approx::assert_abs_diff_eq!(p.prior()[4], 0.105 / 1.005, epsilon = 1e-5);

    // Sum 1.05: rejected.
    assert_invalid(&mutate(CMN_TOML, "\"5\" = 0.10", "\"5\" = 0.15"));
    // Missing key, extra key, non-positive value.
    assert_invalid(&mutate(CMN_TOML, ", \"5\" = 0.10", ""));
    assert_invalid(&mutate(
        CMN_TOML,
        "\"5\" = 0.10",
        "\"5\" = 0.10, \"6\" = 0.0",
    ));
    assert_invalid(&mutate(CMN_TOML, "\"5\" = 0.10", "\"5\" = 0.0"));
}

#[test]
fn rejects_duplicate_tones_and_empty_inventory() {
    let dup = mutate(CMN_TOML, "id = \"2\"", "id = \"1\"");
    assert_invalid(&dup);
    let none = "[pack]\nlect=\"x\"\nversion=\"1\"\ntbu=\"syllable\"\ncapabilities=[]\nbase_accent=\"a\"\nheard_threshold=0.6\nprior={}\n[tolerance]\ncontour=1\nonset=1\noffset=1\nturning_point=1\n[[accent]]\nid=\"a\"\nname=\"A\"\n";
    assert_invalid(none);
}

#[test]
fn rejects_bad_tone_citations() {
    assert_invalid(&mutate(CMN_TOML, "chao = [5, 5]", "chao = []"));
    assert_invalid(&mutate(CMN_TOML, "chao = [5, 5]", "chao = \"whatever\""));
}

#[test]
fn rejects_bad_metadata() {
    assert_invalid(&mutate(
        CMN_TOML,
        "heard_threshold = 0.6",
        "heard_threshold = 1.5",
    ));
    assert_invalid(&mutate(
        CMN_TOML,
        "heard_threshold = 0.6",
        "heard_threshold = -0.1",
    ));
    assert_invalid(&mutate(CMN_TOML, "lect = \"cmn\"", "lect = \"\""));
    assert_invalid(&mutate(CMN_TOML, "version = \"0.3.0\"", "version = \"\""));
    assert_invalid(&mutate(
        CMN_TOML,
        "base_accent = \"cmn-standard\"",
        "base_accent = \"cmn-XX\"",
    ));
}

#[test]
fn rejects_bad_tolerance() {
    assert_invalid(&mutate(CMN_TOML, "contour = 0.7", "contour = 0.0"));
    assert_invalid(&mutate(
        CMN_TOML,
        "turning_point = 0.2",
        "turning_point = -1.0",
    ));
    // The accent-level override is checked too.
    assert_invalid(&mutate(
        CMN_TOML,
        "[accent.tolerance]\ncontour = 0.8",
        "[accent.tolerance]\ncontour = 0.0",
    ));
}

#[test]
fn rejects_bad_unvoiced_ok_and_confusions() {
    assert_invalid(&mutate(
        CMN_TOML,
        "tone = \"3\"\nregion = [0.3, 0.8]",
        "tone = \"9\"\nregion = [0.3, 0.8]",
    ));
    assert_invalid(&mutate(
        CMN_TOML,
        "region = [0.3, 0.8]",
        "region = [0.8, 0.3]",
    ));
    assert_invalid(&mutate(
        CMN_TOML,
        "region = [0.3, 0.8]",
        "region = [0.3, 1.2]",
    ));
    assert_invalid(&mutate(
        CMN_TOML,
        "region = [0.3, 0.8]",
        "region = [-0.1, 0.8]",
    ));
    // Two regions for the same tone are ambiguous.
    let twice = mutate(
        CMN_TOML,
        "[confusions]",
        "[[unvoiced_ok]]\ntone = \"3\"\nregion = [0.1, 0.2]\n\n[confusions]",
    );
    assert_invalid(&twice);
    assert_invalid(&mutate(CMN_TOML, "[\"2\", \"3\"]", "[\"2\", \"9\"]"));
    assert_invalid(&mutate(CMN_TOML, "[\"2\", \"3\"]", "[\"2\", \"2\"]"));
}

#[test]
fn rejects_bad_accents() {
    // Unknown parent.
    assert_invalid(&mutate(
        CMN_TOML,
        "inherits = \"cmn-standard\"",
        "inherits = \"nowhere\"",
    ));
    // Duplicate accent id.
    assert_invalid(&mutate(
        CMN_TOML,
        "id = \"cmn-TW\"",
        "id = \"cmn-standard\"",
    ));
    // Cycles, direct and via a chain.
    let selfloop = mini(
        r#"
[[accent]]
id = "a"
name = "A"
inherits = "a"
"#,
    );
    assert_invalid(&selfloop);
    let cycle = mini(
        r#"
[[accent]]
id = "a"
name = "A"
inherits = "b"
[[accent]]
id = "b"
name = "B"
inherits = "c"
[[accent]]
id = "c"
name = "C"
inherits = "a"
"#,
    );
    assert_invalid(&cycle);
    // No accents at all.
    assert_invalid(&mini(""));
}

#[test]
fn rejects_bad_realize_rules() {
    let rule = |body: &str| {
        mini(&format!(
            "[[accent]]\nid = \"a\"\nname = \"A\"\n[[accent.realize]]\n{body}\n"
        ))
    };
    // Sanity: a well-formed rule loads.
    LanguagePack::from_toml(
        &rule("label = \"x\"\nwhen = { tone = \"1\" }\nchao = [4]"),
        None,
    )
    .unwrap();
    // Both, or neither, of chao and mixture.
    assert_invalid(&rule(
        "label = \"x\"\nwhen = { tone = \"1\" }\nchao = [4]\nmixture = [ { chao = [4], weight = 1.0 } ]",
    ));
    assert_invalid(&rule("label = \"x\"\nwhen = { tone = \"1\" }"));
    // Empty `when` and unknown tone ids in it.
    assert_invalid(&rule("label = \"x\"\nwhen = {}\nchao = [4]"));
    assert_invalid(&rule("label = \"x\"\nwhen = { tone = \"9\" }\nchao = [4]"));
    assert_invalid(&rule("label = \"x\"\nwhen = { prev = \"9\" }\nchao = [4]"));
    // Empty label, empty or non-finite contour, empty mixture.
    assert_invalid(&rule("label = \"\"\nwhen = { tone = \"1\" }\nchao = [4]"));
    assert_invalid(&rule("label = \"x\"\nwhen = { tone = \"1\" }\nchao = []"));
    assert_invalid(&rule(
        "label = \"x\"\nwhen = { tone = \"1\" }\nchao = [nan]",
    ));
    assert_invalid(&rule(
        "label = \"x\"\nwhen = { tone = \"1\" }\nmixture = []",
    ));
    // '#' would make a mixture label ambiguous with a plain one.
    assert_invalid(&rule(
        "label = \"x#0\"\nwhen = { tone = \"1\" }\nchao = [4]",
    ));
    // Duplicate label within one accent.
    let dup = mini(
        r#"
[[accent]]
id = "a"
name = "A"
[[accent.realize]]
label = "x"
when = { tone = "1" }
chao = [4]
[[accent.realize]]
label = "x"
when = { tone = "2" }
chao = [4]
"#,
    );
    assert_invalid(&dup);
}

#[test]
fn a_minimal_pack_loads() {
    let p = LanguagePack::from_toml(&mini(ONE_ACCENT), None).unwrap();
    assert_eq!(p.inventory().len(), 2);
    assert_eq!(p.lect().0, "tst");
}
