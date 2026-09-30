//! Expectation resolution: mixtures, accent inheritance, lexical variants, style blending
//! (spec §6.2 resolution order and §6.3).

use tonekit_core::{
    AccentId, GradingTarget, StyleProfile, StyleTone, ToneId, ToneTarget, WeightedTone,
    CONTOUR_POINTS,
};
use tonekit_pack::{Expectation, LanguagePack, PackError, TargetContext};

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
fn ctx(prev: Option<&str>, fin: bool) -> TargetContext {
    TargetContext {
        index: 1,
        count: 3,
        prev: prev.map(|p| ToneId(p.into())),
        phrase_final: fin,
    }
}
fn tone(s: &str) -> ToneId {
    ToneId(s.into())
}
fn target(main: &str, variants: &[(&str, f32)]) -> ToneTarget {
    ToneTarget {
        tone: tone(main),
        lexical_variants: variants
            .iter()
            .map(|(t, w)| WeightedTone {
                tone: tone(t),
                weight: *w,
            })
            .collect(),
        label: None,
    }
}
fn weight_sum(e: &Expectation) -> f32 {
    e.components.iter().map(|c| c.weight).sum()
}
fn weight_of_tone(e: &Expectation, t: &str) -> f32 {
    e.components
        .iter()
        .filter(|c| c.tone == tone(t))
        .map(|c| c.weight)
        .sum()
}
fn style_of(t: &str, contour: Vec<f32>, n: u32) -> StyleProfile {
    StyleProfile {
        accent: AccentId("cmn-standard".into()),
        tones: vec![StyleTone {
            tone: tone(t),
            contour,
            n,
        }],
        mean_range: 3.0,
    }
}
fn styled(profile: StyleProfile, w: f32) -> GradingTarget {
    GradingTarget {
        style: Some(profile),
        style_weight: w,
        ..std_g()
    }
}

/// A two-tone pack: "1" cites [5,5], "2" cites [2,1,4]; accents come from the caller.
fn mini(accents: &str) -> LanguagePack {
    let toml = format!(
        r#"
[pack]
lect = "tst"
version = "0.0.1"
tbu = "syllable"
capabilities = ["register"]
base_accent = "root"
heard_threshold = 0.6
prior = {{ "1" = 0.5, "2" = 0.5 }}

[[tone]]
id = "1"
name = "high"
chao = [5, 5]

[[tone]]
id = "2"
name = "dip"
chao = [2, 1, 4]

[tolerance]
contour = 0.7
onset = 0.8
offset = 0.8
turning_point = 0.2

{accents}
"#
    );
    LanguagePack::from_toml(&toml, None).unwrap()
}
fn g_for(accent: &str) -> GradingTarget {
    GradingTarget {
        accent: AccentId(accent.into()),
        ..std_g()
    }
}

// ---- cmn: the brief's tests -------------------------------------------------------------

#[test]
fn half_third_nonfinal() {
    let e = cmn()
        .expect_tone(&std_g(), &tone("3"), &ctx(Some("1"), false))
        .unwrap();
    // R47: the half-third, plus the learner's full dip at low weight.
    assert_eq!(e.components.len(), 2);
    approx::assert_abs_diff_eq!(weight_sum(&e), 1.0, epsilon = 1e-4);
    assert_eq!(e.components[0].label, "cmn-standard/t3-half#0");
    assert_eq!(e.components[1].label, "cmn-standard/t3-half#1");
    approx::assert_abs_diff_eq!(e.components[0].weight, 0.75, epsilon = 1e-6);
    approx::assert_abs_diff_eq!(e.components[1].weight, 0.25, epsilon = 1e-6);
    // [2,1] ends at 1; [2,1,4] ends at 4.
    approx::assert_abs_diff_eq!(e.components[0].offset, 1.0, epsilon = 1e-6);
    approx::assert_abs_diff_eq!(e.components[1].offset, 4.0, epsilon = 1e-6);
    assert!(e.components.iter().all(|c| c.tone == tone("3")));
}

#[test]
fn final_third_is_mixture() {
    let e = cmn()
        .expect_tone(&std_g(), &tone("3"), &ctx(Some("1"), true))
        .unwrap();
    assert_eq!(e.components.len(), 2);
    approx::assert_abs_diff_eq!(weight_sum(&e), 1.0, epsilon = 1e-4);
    assert_eq!(e.components[0].label, "cmn-standard/t3-final-dip#0");
    assert_eq!(e.components[1].label, "cmn-standard/t3-final-dip#1");
    approx::assert_abs_diff_eq!(e.components[0].weight, 0.6, epsilon = 1e-6);
    approx::assert_abs_diff_eq!(e.components[1].weight, 0.4, epsilon = 1e-6);
    assert!(e.components.iter().all(|c| c.tone == tone("3")));
}

#[test]
fn neutral_after_third_is_high() {
    let e = cmn()
        .expect_tone(&std_g(), &tone("5"), &ctx(Some("3"), true))
        .unwrap();
    assert!((e.components[0].contour[5] - 4.0).abs() < 1e-3);
    assert!(e.components[0].label.ends_with("t5-after-3"));
}

#[test]
fn neutral_without_prev_uses_default() {
    let e = cmn()
        .expect_tone(&std_g(), &tone("5"), &ctx(None, false))
        .unwrap();
    assert!(e.components[0].label.ends_with("t5-default"));
    assert!((e.components[0].contour[0] - 3.0).abs() < 1e-6);
}

#[test]
fn neutral_specificity_prefers_prev_rule_over_default() {
    // t5-after-4 (2 keys) beats t5-default (1 key) even though t5-default is later in the file.
    for (prev, label, height) in [
        ("1", "t5-after-1", 2.0),
        ("2", "t5-after-2", 3.0),
        ("3", "t5-after-3", 4.0),
        ("4", "t5-after-4", 1.0),
    ] {
        let e = cmn()
            .expect_tone(&std_g(), &tone("5"), &ctx(Some(prev), false))
            .unwrap();
        assert_eq!(e.components[0].label, format!("cmn-standard/{label}"));
        assert!(e.components[0]
            .contour
            .iter()
            .all(|v| (v - height).abs() < 1e-6));
    }
    // A previous neutral tone has no t5-after-5 rule: falls back to the default.
    let e = cmn()
        .expect_tone(&std_g(), &tone("5"), &ctx(Some("5"), false))
        .unwrap();
    assert_eq!(e.components[0].label, "cmn-standard/t5-default");
}

#[test]
fn tw_overrides_t3_and_inherits_neutral() {
    let g = GradingTarget {
        accent: AccentId("cmn-TW".into()),
        ..std_g()
    };
    let p = cmn();
    assert!(p
        .expect_tone(&g, &tone("3"), &ctx(Some("1"), true))
        .unwrap()
        .components[0]
        .label
        .starts_with("cmn-TW/t3-low"));
    assert!(p
        .expect_tone(&g, &tone("5"), &ctx(Some("1"), false))
        .unwrap()
        .components[0]
        .label
        .starts_with("cmn-standard/t5-after-1"));
}

#[test]
fn tw_t3_mixture_is_80_20() {
    let g = g_for("cmn-TW");
    let e = cmn()
        .expect_tone(&g, &tone("3"), &ctx(Some("1"), true))
        .unwrap();
    assert_eq!(e.components.len(), 2);
    approx::assert_abs_diff_eq!(e.components[0].weight, 0.8, epsilon = 1e-6);
    approx::assert_abs_diff_eq!(e.components[1].weight, 0.2, epsilon = 1e-6);
    // [2,1] then [2,1,3]: the second ends at 3.
    approx::assert_abs_diff_eq!(e.components[0].offset, 1.0, epsilon = 1e-6);
    approx::assert_abs_diff_eq!(e.components[1].offset, 3.0, epsilon = 1e-6);
    // TW's t3-low matches phrase-medial T3 too, and a child accent's match wins over the
    // parent's t3-half without the parent being consulted.
    let m = cmn()
        .expect_tone(&g, &tone("3"), &ctx(Some("1"), false))
        .unwrap();
    assert!(m.components[0].label.starts_with("cmn-TW/t3-low"));
}

#[test]
fn unknown_accent_errors() {
    let g = GradingTarget {
        accent: AccentId("cmn-XX".into()),
        ..std_g()
    };
    assert!(matches!(
        cmn().expect_tone(&g, &tone("1"), &ctx(None, false)),
        Err(PackError::UnknownAccent(_))
    ));
    assert_eq!(
        cmn()
            .expect(&g, &target("1", &[]), &ctx(None, false))
            .unwrap_err(),
        PackError::UnknownAccent(AccentId("cmn-XX".into()))
    );
}

#[test]
fn unknown_tone_errors() {
    let p = cmn();
    assert_eq!(
        p.expect_tone(&std_g(), &tone("9"), &ctx(None, false))
            .unwrap_err(),
        PackError::UnknownTone(tone("9"))
    );
    // Main tone, variant tone and previous tone are all checked.
    assert_eq!(
        p.expect(&std_g(), &target("9", &[]), &ctx(None, false))
            .unwrap_err(),
        PackError::UnknownTone(tone("9"))
    );
    assert_eq!(
        p.expect(&std_g(), &target("1", &[("8", 0.2)]), &ctx(None, false))
            .unwrap_err(),
        PackError::UnknownTone(tone("8"))
    );
    assert_eq!(
        p.expect_tone(&std_g(), &tone("5"), &ctx(Some("7"), false))
            .unwrap_err(),
        PackError::UnknownTone(tone("7"))
    );
}

// ---- citation, knot expansion, tolerance ------------------------------------------------

#[test]
fn citation_is_used_when_no_rule_matches() {
    let e = cmn()
        .expect_tone(&std_g(), &tone("1"), &ctx(Some("4"), false))
        .unwrap();
    assert_eq!(e.components.len(), 1);
    let c = &e.components[0];
    assert_eq!(c.label, "cmn-standard/citation");
    assert_eq!(c.tone, tone("1"));
    assert_eq!(c.weight, 1.0);
    assert_eq!(c.contour.len(), CONTOUR_POINTS);
    assert!(c.contour.iter().all(|v| (v - 5.0).abs() < 1e-6));
    assert_eq!((c.onset, c.offset), (5.0, 5.0));

    // The citation label carries the graded accent, even when the rule search walked up.
    let e = cmn()
        .expect_tone(&g_for("cmn-TW"), &tone("4"), &ctx(None, true))
        .unwrap();
    assert_eq!(e.components[0].label, "cmn-TW/citation");
}

#[test]
fn chao_knots_interpolate_linearly_over_contour_points() {
    let rise = cmn()
        .expect_tone(&std_g(), &tone("2"), &ctx(Some("1"), false))
        .unwrap()
        .components
        .remove(0);
    assert_eq!(rise.contour.len(), CONTOUR_POINTS);
    for (i, v) in rise.contour.iter().enumerate() {
        let want = 3.0 + 2.0 * i as f32 / (CONTOUR_POINTS - 1) as f32;
        approx::assert_abs_diff_eq!(*v, want, epsilon = 1e-5);
    }
    assert_eq!((rise.onset, rise.offset), (3.0, 5.0));

    // Three knots [2,1,4] at u = 0, 0.5, 1 with u = i/(n-1).
    let p = mini("[[accent]]\nid = \"root\"\nname = \"R\"\n");
    let dip = p
        .expect_tone(&g_for("root"), &tone("2"), &ctx(None, false))
        .unwrap()
        .components
        .remove(0);
    let at = |i: usize| dip.contour[i];
    approx::assert_abs_diff_eq!(at(0), 2.0, epsilon = 1e-5);
    approx::assert_abs_diff_eq!(at(3), 2.0 - 2.0 * (1.0 / 3.0), epsilon = 1e-5);
    approx::assert_abs_diff_eq!(at(6), 1.0 + 6.0 * (2.0 / 3.0 - 0.5), epsilon = 1e-5);
    approx::assert_abs_diff_eq!(at(9), 4.0, epsilon = 1e-5);
    assert_eq!((dip.onset, dip.offset), (2.0, 4.0));
}

#[test]
fn tolerance_comes_from_pack_default_overridden_by_accent() {
    let p = cmn();
    let std = &p
        .expect_tone(&std_g(), &tone("1"), &ctx(None, false))
        .unwrap()
        .components[0];
    assert_eq!(std.sigma.contour, 0.7);
    assert_eq!(std.sigma.onset, 0.8);
    assert_eq!(std.sigma.offset, 0.8);
    assert_eq!(std.sigma.turning_point, 0.2);
    // cmn-TW overrides only `contour`.
    let tw = &p
        .expect_tone(&g_for("cmn-TW"), &tone("1"), &ctx(None, false))
        .unwrap()
        .components[0];
    assert_eq!(tw.sigma.contour, 0.8);
    assert_eq!(tw.sigma.onset, 0.8);
    assert_eq!(tw.sigma.offset, 0.8);
    assert_eq!(tw.sigma.turning_point, 0.2);
    // The graded accent's tolerance applies to every component, including inherited rules.
    let inherited = &p
        .expect_tone(&g_for("cmn-TW"), &tone("5"), &ctx(Some("1"), false))
        .unwrap()
        .components[0];
    assert!(inherited.label.starts_with("cmn-standard/"));
    assert_eq!(inherited.sigma.contour, 0.8);
}

#[test]
fn tolerance_chain_overrides_root_first() {
    // grandchild -> child -> root; child sets contour+onset, grandchild sets onset only.
    let p = mini(
        r#"
[[accent]]
id = "grandchild"
name = "G"
inherits = "child"
[accent.tolerance]
onset = 0.3

[[accent]]
id = "child"
name = "C"
inherits = "root"
[accent.tolerance]
contour = 0.5
onset = 0.6
turning_point = 0.1

[[accent]]
id = "root"
name = "R"
"#,
    );
    let sigma = |a: &str| {
        p.expect_tone(&g_for(a), &tone("1"), &ctx(None, false))
            .unwrap()
            .components
            .remove(0)
            .sigma
    };
    let r = sigma("root");
    assert_eq!(
        (r.contour, r.onset, r.offset, r.turning_point),
        (0.7, 0.8, 0.8, 0.2)
    );
    let c = sigma("child");
    assert_eq!(
        (c.contour, c.onset, c.offset, c.turning_point),
        (0.5, 0.6, 0.8, 0.1)
    );
    let g = sigma("grandchild");
    assert_eq!(
        (g.contour, g.onset, g.offset, g.turning_point),
        (0.5, 0.3, 0.8, 0.1)
    );
}

// ---- resolution order --------------------------------------------------------------------

#[test]
fn specificity_beats_file_order_and_ties_go_to_the_first_rule() {
    let p = mini(
        r#"
[[accent]]
id = "root"
name = "R"

[[accent.realize]]
label = "loose"
when = { tone = "1" }
chao = [1]

[[accent.realize]]
label = "tight"
when = { tone = "1", prev = "2", phrase_final = true }
chao = [2]

[[accent.realize]]
label = "mid-a"
when = { tone = "1", prev = "1" }
chao = [3]

[[accent.realize]]
label = "mid-b"
when = { tone = "1", phrase_final = true }
chao = [4]
"#,
    );
    let g = g_for("root");
    let label = |prev: Option<&str>, fin: bool| {
        p.expect_tone(&g, &tone("1"), &ctx(prev, fin))
            .unwrap()
            .components
            .remove(0)
            .label
    };
    assert_eq!(label(Some("2"), true), "root/tight"); // 3 keys beats 2 and 1
    assert_eq!(label(Some("1"), true), "root/mid-a"); // 2-key tie: file order
    assert_eq!(label(None, true), "root/mid-b");
    assert_eq!(label(Some("1"), false), "root/mid-a");
    assert_eq!(label(None, false), "root/loose");
}

#[test]
fn a_rule_without_a_matching_prev_does_not_match_when_prev_is_absent() {
    let p = mini(
        r#"
[[accent]]
id = "root"
name = "R"
[[accent.realize]]
label = "after-1"
when = { tone = "1", prev = "1" }
chao = [1]
"#,
    );
    let e = p
        .expect_tone(&g_for("root"), &tone("1"), &ctx(None, false))
        .unwrap();
    assert_eq!(e.components[0].label, "root/citation");
}

#[test]
fn child_accent_rule_wins_even_if_less_specific_than_the_parents() {
    let p = mini(
        r#"
[[accent]]
id = "root"
name = "R"
[[accent.realize]]
label = "specific"
when = { tone = "1", prev = "1", phrase_final = true }
chao = [1]

[[accent]]
id = "child"
name = "C"
inherits = "root"
[[accent.realize]]
label = "loose"
when = { tone = "1" }
chao = [2]
"#,
    );
    let e = p
        .expect_tone(&g_for("child"), &tone("1"), &ctx(Some("1"), true))
        .unwrap();
    assert_eq!(e.components[0].label, "child/loose");
    let e = p
        .expect_tone(&g_for("root"), &tone("1"), &ctx(Some("1"), true))
        .unwrap();
    assert_eq!(e.components[0].label, "root/specific");
}

// ---- lexical variants --------------------------------------------------------------------

#[test]
fn lexical_variants_weight_components() {
    let e = cmn()
        .expect(
            &std_g(),
            &target("2", &[("1", 0.3)]),
            &ctx(Some("1"), false),
        )
        .unwrap();
    approx::assert_abs_diff_eq!(weight_sum(&e), 1.0, epsilon = 1e-4);
    approx::assert_abs_diff_eq!(weight_of_tone(&e, "1"), 0.3, epsilon = 1e-4);
    approx::assert_abs_diff_eq!(weight_of_tone(&e, "2"), 0.7, epsilon = 1e-4);
    // Each component realises its own tone.
    assert!(e
        .components
        .iter()
        .filter(|c| c.tone == tone("1"))
        .all(|c| (c.contour[0] - 5.0).abs() < 1e-6));
}

#[test]
fn lexical_variants_multiply_into_mixtures() {
    // Main T3 phrase-final is a 0.6/0.4 mixture; variant T4 has weight 0.25.
    let e = cmn()
        .expect(
            &std_g(),
            &target("3", &[("4", 0.25)]),
            &ctx(Some("1"), true),
        )
        .unwrap();
    assert_eq!(e.components.len(), 3);
    approx::assert_abs_diff_eq!(weight_sum(&e), 1.0, epsilon = 1e-4);
    approx::assert_abs_diff_eq!(e.components[0].weight, 0.75 * 0.6, epsilon = 1e-5);
    approx::assert_abs_diff_eq!(e.components[1].weight, 0.75 * 0.4, epsilon = 1e-5);
    approx::assert_abs_diff_eq!(e.components[2].weight, 0.25, epsilon = 1e-5);
    assert_eq!(e.components[2].tone, tone("4"));
}

#[test]
fn no_variants_equals_expect_tone() {
    let p = cmn();
    let c = ctx(Some("2"), true);
    assert_eq!(
        p.expect(&std_g(), &target("3", &[]), &c).unwrap(),
        p.expect_tone(&std_g(), &tone("3"), &c).unwrap()
    );
}

#[test]
fn variants_may_take_the_whole_weight() {
    // Σ variants = 1 leaves the main tone with weight 0; its components are omitted.
    let e = cmn()
        .expect(
            &std_g(),
            &target("2", &[("1", 1.0)]),
            &ctx(Some("1"), false),
        )
        .unwrap();
    assert!(e.components.iter().all(|c| c.tone == tone("1")));
    approx::assert_abs_diff_eq!(weight_sum(&e), 1.0, epsilon = 1e-6);
}

#[test]
fn rejects_variant_weights_over_one_or_negative() {
    let p = cmn();
    let c = ctx(Some("1"), false);
    for variants in [
        vec![("1", 0.7), ("3", 0.5)],
        vec![("1", 1.2)],
        vec![("1", -0.1)],
        vec![("1", f32::NAN)],
    ] {
        let r = p.expect(&std_g(), &target("2", &variants), &c);
        assert!(
            matches!(r, Err(PackError::Invalid(_))),
            "{variants:?}: {r:?}"
        );
    }
}

// ---- style blending ----------------------------------------------------------------------

#[test]
fn style_blends_contour() {
    // T1 is [5,5]; style T1 is 4.0 throughout with n = 5; weight 0.5 -> 4.5.
    let g = styled(style_of("1", vec![4.0; CONTOUR_POINTS], 5), 0.5);
    let e = cmn()
        .expect_tone(&g, &tone("1"), &ctx(None, false))
        .unwrap();
    let c = &e.components[0];
    assert_eq!(c.contour.len(), CONTOUR_POINTS);
    assert!(
        c.contour.iter().all(|v| (v - 4.5).abs() < 1e-5),
        "{:?}",
        c.contour
    );
    // Onset and offset are the blended endpoints.
    approx::assert_abs_diff_eq!(c.onset, 4.5, epsilon = 1e-5);
    approx::assert_abs_diff_eq!(c.offset, 4.5, epsilon = 1e-5);
    // The label is unchanged by blending; tolerance too.
    assert_eq!(c.label, "cmn-standard/citation");
    assert_eq!(c.sigma.contour, 0.7);
}

#[test]
fn style_blends_endpoints_independently() {
    // Component T2 [3,5]; style rises from 1 to 2. Blend at 0.25: onset 0.75*3+0.25*1 = 2.5,
    // offset 0.75*5+0.25*2 = 4.25.
    let mut style = vec![0.0; CONTOUR_POINTS];
    for (i, v) in style.iter_mut().enumerate() {
        *v = 1.0 + i as f32 / (CONTOUR_POINTS - 1) as f32;
    }
    let g = styled(style_of("2", style, 12), 0.25);
    let c = cmn()
        .expect_tone(&g, &tone("2"), &ctx(Some("1"), false))
        .unwrap()
        .components
        .remove(0);
    approx::assert_abs_diff_eq!(c.onset, 2.5, epsilon = 1e-5);
    approx::assert_abs_diff_eq!(c.offset, 4.25, epsilon = 1e-5);
    assert_eq!(c.onset, c.contour[0]);
    assert_eq!(c.offset, c.contour[CONTOUR_POINTS - 1]);
}

#[test]
fn style_needs_five_observations_and_a_matching_tone() {
    let plain = cmn()
        .expect_tone(&std_g(), &tone("1"), &ctx(None, false))
        .unwrap();
    // n = 4: ignored.
    let g = styled(style_of("1", vec![4.0; CONTOUR_POINTS], 4), 0.5);
    assert_eq!(
        cmn()
            .expect_tone(&g, &tone("1"), &ctx(None, false))
            .unwrap(),
        plain
    );
    // Style for another tone: ignored.
    let g = styled(style_of("4", vec![4.0; CONTOUR_POINTS], 50), 0.5);
    assert_eq!(
        cmn()
            .expect_tone(&g, &tone("1"), &ctx(None, false))
            .unwrap(),
        plain
    );
    // Weight 0 leaves the accent expectation untouched.
    let g = styled(style_of("1", vec![4.0; CONTOUR_POINTS], 50), 0.0);
    assert_eq!(
        cmn()
            .expect_tone(&g, &tone("1"), &ctx(None, false))
            .unwrap(),
        plain
    );
}

#[test]
fn style_weight_is_clamped_to_unit_interval() {
    let full = styled(style_of("1", vec![4.0; CONTOUR_POINTS], 9), 7.0);
    let c = cmn()
        .expect_tone(&full, &tone("1"), &ctx(None, false))
        .unwrap()
        .components
        .remove(0);
    assert!(c.contour.iter().all(|v| (v - 4.0).abs() < 1e-6));
    let neg = styled(style_of("1", vec![4.0; CONTOUR_POINTS], 9), -3.0);
    let c = cmn()
        .expect_tone(&neg, &tone("1"), &ctx(None, false))
        .unwrap()
        .components
        .remove(0);
    assert!(c.contour.iter().all(|v| (v - 5.0).abs() < 1e-6));
}

#[test]
fn style_applies_per_component_tone_including_variants_and_mixtures() {
    // Target T3 (phrase-final mixture) with variant T1: each component blends against the style
    // contour of its own tone; T3 has no style entry and stays as resolved.
    let g = styled(style_of("1", vec![3.0; CONTOUR_POINTS], 8), 1.0);
    let e = cmn()
        .expect(&g, &target("3", &[("1", 0.5)]), &ctx(Some("1"), true))
        .unwrap();
    for c in &e.components {
        if c.tone == tone("1") {
            assert!(c.contour.iter().all(|v| (v - 3.0).abs() < 1e-6));
        } else {
            assert!(c.contour.iter().any(|v| (v - 3.0).abs() > 0.5));
        }
    }
}

#[test]
fn style_contour_of_another_length_is_resampled() {
    // A 2-point style contour [1, 3] is stretched over CONTOUR_POINTS.
    let g = styled(style_of("1", vec![1.0, 3.0], 5), 1.0);
    let c = cmn()
        .expect_tone(&g, &tone("1"), &ctx(None, false))
        .unwrap()
        .components
        .remove(0);
    assert_eq!(c.contour.len(), CONTOUR_POINTS);
    approx::assert_abs_diff_eq!(c.contour[0], 1.0, epsilon = 1e-5);
    approx::assert_abs_diff_eq!(c.contour[CONTOUR_POINTS - 1], 3.0, epsilon = 1e-5);
    approx::assert_abs_diff_eq!(c.contour[3], 1.0 + 2.0 / 3.0, epsilon = 1e-5);
}

#[test]
fn rejects_malformed_style() {
    let ok = ctx(None, false);
    for profile in [
        style_of("1", vec![], 9),
        style_of("1", vec![f32::NAN; CONTOUR_POINTS], 9),
    ] {
        let r = cmn().expect_tone(&styled(profile, 0.5), &tone("1"), &ok);
        assert!(matches!(r, Err(PackError::Invalid(_))), "{r:?}");
    }
    let r = cmn().expect_tone(
        &styled(style_of("1", vec![4.0; CONTOUR_POINTS], 9), f32::NAN),
        &tone("1"),
        &ok,
    );
    assert!(matches!(r, Err(PackError::Invalid(_))), "{r:?}");
    // A malformed profile for a tone that is not being expected is not consulted.
    let r = cmn().expect_tone(&styled(style_of("4", vec![], 9), 0.5), &tone("1"), &ok);
    assert!(r.is_ok());
}
