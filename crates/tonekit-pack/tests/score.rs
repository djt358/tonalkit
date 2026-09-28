//! Calibrated likelihoods, LLR, judgement and deltas (spec §7.1).
//!
//! Shapes are hand-built from Chao knots (exact, no extraction jitter, ruling R23) with
//! `voiced_weights` all 1.0 unless a test says otherwise.

use proptest::prelude::*;
use tonekit_core::{
    AccentId, DeltaKind, GradingTarget, MeasureIssue, Measured, TbuSpan, ToneId, ToneShape,
    ToneTarget, WeightedTone, CONTOUR_POINTS,
};
use tonekit_pack::{widen_for, LanguagePack, PackError, TargetContext};

const CMN_TOML: &str = include_str!("../../../packs/cmn/cmn.toml");
const CMN_CALIB: &str = include_str!("../../../packs/cmn/cmn.calib.json");

fn cmn() -> LanguagePack {
    LanguagePack::from_toml(CMN_TOML, Some(CMN_CALIB)).unwrap()
}
fn std_g() -> GradingTarget {
    g_for("cmn-standard")
}
fn g_for(accent: &str) -> GradingTarget {
    GradingTarget {
        accent: AccentId(accent.into()),
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
fn target(t: &str) -> ToneTarget {
    ToneTarget {
        tone: tone(t),
        lexical_variants: vec![],
        label: None,
    }
}
fn target_with(t: &str, variants: &[(&str, f32)]) -> ToneTarget {
    ToneTarget {
        lexical_variants: variants
            .iter()
            .map(|(v, w)| WeightedTone {
                tone: tone(v),
                weight: *w,
            })
            .collect(),
        ..target(t)
    }
}

/// The turning-point rule of shape extraction (ruling R4) on an unsmoothed contour: the interior
/// extremum at `u` in (0.1, 0.9) that stands at least 0.5 Chao beyond both endpoints (the larger
/// excursion if both do), the centre of a plateau of equal values.
fn turning_point(c: &[f32]) -> Option<f32> {
    let n = c.len();
    if n < 3 {
        return None;
    }
    let (first, last) = (f64::from(c[0]), f64::from(c[n - 1]));
    let centre = |sign: f64| {
        let v: Vec<f64> = c.iter().map(|&y| sign * f64::from(y)).collect();
        let best = v.iter().copied().fold(f64::NEG_INFINITY, f64::max);
        let a = v.iter().position(|&y| y >= best - 1e-9).unwrap();
        let b = v.iter().rposition(|&y| y >= best - 1e-9).unwrap();
        (sign * best, 0.5 * (a + b) as f64 / (n - 1) as f64)
    };
    let (vmin, umin) = centre(-1.0);
    let (vmax, umax) = centre(1.0);
    [
        ((first - vmin).min(last - vmin), umin),
        ((vmax - first).min(vmax - last), umax),
    ]
    .into_iter()
    .filter(|&(e, u)| e >= 0.5 && u > 0.1 && u < 0.9)
    .max_by(|a, b| a.0.total_cmp(&b.0))
    .map(|(_, u)| u as f32)
}

/// A shape whose contour is `contour`; every derived field follows from it.
fn shape_from_contour(contour: Vec<f32>) -> ToneShape {
    let n = contour.len();
    let min = contour.iter().copied().fold(f32::INFINITY, f32::min);
    let max = contour.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    ToneShape {
        span: TbuSpan {
            start_frame: 0,
            end_frame: 30,
        },
        onset: contour[0],
        offset: contour[n - 1],
        mean: contour.iter().sum::<f32>() / n as f32,
        slope: 0.0,
        curvature: 0.0,
        turning_point: turning_point(&contour),
        range: max - min,
        duration_ms: 300.0,
        voiced_fraction: 1.0,
        f0_confidence: 1.0,
        phonation: None,
        voiced_weights: vec![1.0; n],
        contour,
    }
}

/// Chao knots linearly interpolated at `u_k = k/9` (10 points).
fn interpolate(knots: &[f32]) -> Vec<f32> {
    let last = knots.len() - 1;
    (0..CONTOUR_POINTS)
        .map(|k| {
            let pos = k as f32 / (CONTOUR_POINTS - 1) as f32 * last as f32;
            let j = (pos.floor() as usize).min(last.saturating_sub(1));
            if last == 0 {
                knots[0]
            } else {
                knots[j] + (pos - j as f32) * (knots[j + 1] - knots[j])
            }
        })
        .collect()
}
fn shape(knots: Vec<f32>) -> ToneShape {
    shape_from_contour(interpolate(&knots))
}

fn judge_of(knots: Vec<f32>, t: &str) -> tonekit_core::ToneJudgement {
    cmn()
        .judge(
            &std_g(),
            &shape(knots),
            &target(t),
            &ctx(Some("1"), false),
            &[],
        )
        .unwrap()
}
fn llr_of(x: &ToneShape, t: &str, issues: &[MeasureIssue]) -> f32 {
    cmn()
        .judge(&std_g(), x, &target(t), &ctx(Some("1"), false), issues)
        .unwrap()
        .llr_target
}
fn assert_all_finite(j: &tonekit_core::ToneJudgement) {
    assert!(j.llr_target.is_finite(), "llr {}", j.llr_target);
    assert!(j.loglik.iter().all(|v| v.is_finite() && *v >= -1.0e6));
    assert!(j.llr_target.abs() <= 1.0e6);
    if let Some(d) = j.distance {
        assert!(d.is_finite() && d >= 0.0, "distance {d}");
    }
    assert!(j.deltas.iter().all(|d| d.amount.is_finite()));
}

// ---- the brief's tests ------------------------------------------------------------------

#[test]
fn correct_tone_has_positive_llr_wrong_negative() {
    let x = shape(vec![5., 1.]); // a clean T4
    let j4 = cmn()
        .judge(&std_g(), &x, &target("4"), &ctx(Some("1"), false), &[])
        .unwrap();
    let j2 = cmn()
        .judge(&std_g(), &x, &target("2"), &ctx(Some("1"), false), &[])
        .unwrap();
    assert!(j4.llr_target > 0.0 && j2.llr_target < 0.0);
    assert_eq!(j4.heard, Some(ToneId("4".into())));
    assert_eq!(j4.loglik.len(), 5);
}

#[test]
fn distance_is_zero_ish_for_template() {
    assert!(judge_of(vec![3., 5.], "2").distance.unwrap() < 0.2);
}

#[test]
fn t3_creak_gap_not_penalized() {
    // Review Focus 4. Ruling R7: the clean baseline uses the same ctx as the creaky shape.
    let mut x = shape(vec![2., 1., 4.]);
    for k in 4..7 {
        x.voiced_weights[k] = 0.0;
        x.contour[k] = 3.0;
    }
    let clean = cmn()
        .judge(
            &std_g(),
            &shape(vec![2., 1., 4.]),
            &target("3"),
            &ctx(Some("1"), true),
            &[],
        )
        .unwrap()
        .llr_target;
    assert!(
        (cmn()
            .judge(&std_g(), &x, &target("3"), &ctx(Some("1"), true), &[])
            .unwrap()
            .llr_target
            - clean)
            .abs()
            < 0.5
    );
    // Added (R26 follow-up): the excused points also leave the distance to the best component
    // (the full dip) at zero. With T3 creak counted as evidence it would be about 0.7.
    let creaky = cmn()
        .judge(&std_g(), &x, &target("3"), &ctx(Some("1"), true), &[])
        .unwrap();
    assert_eq!(
        creaky.component.as_deref(),
        Some("cmn-standard/t3-final-dip#0")
    );
    assert!(creaky.distance.unwrap() < 1e-3, "{:?}", creaky.distance);
}

#[test]
fn too_short_uses_endpoints_only() {
    // Review Focus 5.
    let mut x = shape(vec![5., 1.]);
    for k in 1..9 {
        x.contour[k] = 5.0; // mangled middle
    }
    let j = cmn()
        .judge(
            &std_g(),
            &x,
            &target("4"),
            &ctx(None, false),
            &[MeasureIssue::TooShort],
        )
        .unwrap();
    assert!(j.llr_target > 0.0);
    assert!(matches!(j.measured, Measured::Partial { .. }));
    // Added (R26 follow-up): the endpoints are exactly T4's, so with the interior ignored the
    // distance is zero and the issue is carried through; with the mangled middle counted it
    // would be several Chao.
    assert!(j.distance.unwrap() < 1e-3, "{:?}", j.distance);
    assert_eq!(
        j.measured,
        Measured::Partial {
            issues: vec![MeasureIssue::TooShort]
        }
    );
}

#[test]
fn too_short_ignores_the_contour_interior_entirely() {
    // Under TooShort every tone is scored on onset and offset alone, so what happens between
    // them changes nothing: not the llr, not the distance, not any loglik.
    let clean = shape(vec![5., 1.]);
    let mut mangled = clean.clone();
    for k in 1..9 {
        mangled.contour[k] = 5.0;
    }
    let c = ctx(None, false);
    let judge = |x: &ToneShape, issues: &[MeasureIssue]| {
        cmn().judge(&std_g(), x, &target("4"), &c, issues).unwrap()
    };
    let short = [MeasureIssue::TooShort];
    let (a, b) = (judge(&clean, &short), judge(&mangled, &short));
    assert_eq!(a.llr_target, b.llr_target);
    assert_eq!(a.distance, b.distance);
    assert_eq!(a.loglik, b.loglik);
    // Without the issue the mangled middle does count.
    // (T4 still wins the background either way, so the llr saturates; the likelihood and the
    // distance are what move.)
    let (a, b) = (judge(&clean, &[]), judge(&mangled, &[]));
    assert!(b.loglik[3] < a.loglik[3] - 1.0);
    assert!(b.distance.unwrap() > a.distance.unwrap() + 1.0);
}

#[test]
fn deltas_point_the_right_way() {
    let j = judge_of(vec![3., 4.], "1"); // too low a start for T1
    assert_eq!(j.deltas[0].kind, DeltaKind::StartHigher);
}

#[test]
fn low_snr_widens_and_suppresses_deltas() {
    // The same shape, judged twice. T1 vs [3, 4]: a clear mismatch with deltas to give.
    let x = shape(vec![3., 4.]);
    let plain = cmn()
        .judge(&std_g(), &x, &target("1"), &ctx(Some("1"), false), &[])
        .unwrap();
    let noisy = cmn()
        .judge(
            &std_g(),
            &x,
            &target("1"),
            &ctx(Some("1"), false),
            &[MeasureIssue::LowSnr],
        )
        .unwrap();
    assert!(!plain.deltas.is_empty());
    assert!(noisy.deltas.is_empty());
    assert!(plain.llr_target < 0.0 && noisy.llr_target < 0.0);
    assert!(
        noisy.llr_target.abs() < plain.llr_target.abs(),
        "widened tolerance must shrink the LLR: {} vs {}",
        noisy.llr_target,
        plain.llr_target
    );
    // The same holds for a good match: the evidence for it gets weaker, not stronger.
    let good = shape(vec![5., 5.]);
    assert!(llr_of(&good, "1", &[MeasureIssue::LowSnr]).abs() < llr_of(&good, "1", &[]).abs());
    assert_eq!(
        noisy.measured,
        Measured::Partial {
            issues: vec![MeasureIssue::LowSnr]
        }
    );
}

#[test]
fn tw_prefers_low_t3_final() {
    // A phrase-final T3 that only falls: "low" T3 is the Taiwan realisation.
    let x = shape(vec![2., 1.]);
    let c = ctx(Some("1"), true);
    let tw = cmn()
        .judge(&g_for("cmn-TW"), &x, &target("3"), &c, &[])
        .unwrap();
    let standard = cmn().judge(&std_g(), &x, &target("3"), &c, &[]).unwrap();
    assert!(
        tw.llr_target > standard.llr_target,
        "TW {} vs standard {}",
        tw.llr_target,
        standard.llr_target
    );
}

proptest! {
    #[test]
    fn moving_toward_expectation_never_lowers_llr(t in 0.0f32..1.0) {
        // x = lerp(shape [3,4] (bad T4), shape [5,1] (template T4), t).
        let bad = interpolate(&[3., 4.]);
        let template = interpolate(&[5., 1.]);
        let at = |t: f32| {
            let c: Vec<f32> = bad.iter().zip(&template).map(|(a, b)| a + t * (b - a)).collect();
            llr_of(&shape_from_contour(c), "4", &[])
        };
        // The llr is non-decreasing along the path, checked in steps of 0.1 up to the template.
        let mut prev = at(t);
        let mut s = t;
        while s < 1.0 {
            s = (s + 0.1).min(1.0);
            let next = at(s);
            prop_assert!(next >= prev - 1e-4, "llr fell from {prev} to {next} at t={s}");
            prev = next;
        }
    }
}

// ---- formulas ---------------------------------------------------------------------------

#[test]
fn widen_for_rules() {
    use MeasureIssue::*;
    assert_eq!(widen_for(&[]), 1.0);
    assert_eq!(widen_for(&[TooShort]), 1.0);
    assert_eq!(widen_for(&[Unvoiced]), 1.0);
    assert_eq!(widen_for(&[TooShort, Unvoiced]), 1.0);
    for w in [LowSnr, Clipped, ColdStartRegister] {
        assert_eq!(widen_for(&[w]), 1.5);
        assert_eq!(widen_for(&[TooShort, w]), 1.5);
    }
    assert_eq!(widen_for(&[LowSnr, Clipped, ColdStartRegister]), 1.5);
}

#[test]
fn tone_loglik_matches_the_closed_form() {
    // T1 after T1 is the citation [5,5]; σ = (0.7, 0.8, 0.8). An exact match has d² = 0, so
    // ll = −ln(σc·σon·σoff), and widening multiplies every σ by 1.5.
    let x = shape(vec![5., 5.]);
    let c = ctx(Some("1"), false);
    let ll = cmn()
        .tone_loglik(&std_g(), &x, &tone("1"), &c, &[])
        .unwrap();
    approx::assert_abs_diff_eq!(ll, -(0.7f32 * 0.8 * 0.8).ln(), epsilon = 1e-4);
    for issue in [
        MeasureIssue::LowSnr,
        MeasureIssue::Clipped,
        MeasureIssue::ColdStartRegister,
    ] {
        let wide = cmn()
            .tone_loglik(&std_g(), &x, &tone("1"), &c, &[issue])
            .unwrap();
        approx::assert_abs_diff_eq!(wide, -(0.7f32 * 0.8 * 0.8 * 3.375).ln(), epsilon = 1e-4);
    }
    // TooShort and Unvoiced do not widen.
    let short = cmn()
        .tone_loglik(&std_g(), &x, &tone("1"), &c, &[MeasureIssue::TooShort])
        .unwrap();
    approx::assert_abs_diff_eq!(short, ll, epsilon = 1e-4);
}

#[test]
fn onset_and_offset_terms_carry_weight_one_half() {
    // Endpoint-only mismatch under TooShort (contour term dropped): x = [5, 3] vs T1 [5, 5].
    // d² = 0.5·(0/0.8)² + 0.5·(−2/0.8)² = 3.125.
    let x = shape(vec![5., 3.]);
    let j = cmn()
        .judge(
            &std_g(),
            &x,
            &target("1"),
            &ctx(Some("1"), false),
            &[MeasureIssue::TooShort],
        )
        .unwrap();
    approx::assert_abs_diff_eq!(j.distance.unwrap(), 3.125f32.sqrt(), epsilon = 1e-4);
}

#[test]
fn weights_floor_at_a_quarter() {
    // T4 [5,1] with one interior point 2 Chao off. Under weights w_k = max(v_k, 0.25):
    //   v = 1:  WRMS² = 4/10;   v = 0: WRMS² = 0.25·4/9.25.
    let c = ctx(Some("1"), false);
    let ll = |vw: f32| {
        let mut x = shape(vec![5., 1.]);
        x.contour[2] += 2.0;
        x.voiced_weights[2] = vw;
        cmn()
            .tone_loglik(&std_g(), &x, &tone("4"), &c, &[])
            .unwrap()
    };
    let base = -(0.7f32 * 0.8 * 0.8).ln();
    let expect = |wrms2: f32| base - 0.5 * wrms2 / 0.49;
    approx::assert_abs_diff_eq!(ll(1.0), expect(4.0 / 10.0), epsilon = 1e-3);
    approx::assert_abs_diff_eq!(ll(0.0), expect(0.25 * 4.0 / 9.25), epsilon = 1e-3);
    approx::assert_abs_diff_eq!(ll(0.25), ll(0.0), epsilon = 1e-4);
    assert!(ll(0.5) < ll(0.25) && ll(1.0) < ll(0.5));
}

#[test]
fn unvoiced_ok_region_ignores_unvoiced_points_for_t3_only() {
    // Whatever garbage sits at unvoiced points inside T3's region [0.3, 0.8] is not evidence.
    let c = ctx(Some("1"), true);
    let creaky = |garbage: f32| {
        let mut x = shape(vec![2., 1., 4.]);
        for k in 4..7 {
            x.voiced_weights[k] = 0.0;
            x.contour[k] = garbage;
        }
        x
    };
    let ll3 = |g: f32| {
        cmn()
            .tone_loglik(&std_g(), &creaky(g), &tone("3"), &c, &[])
            .unwrap()
    };
    assert_eq!(ll3(3.0), ll3(9.0));
    assert_eq!(ll3(3.0), ll3(-4.0));
    // The same points do count against a tone without a region.
    let ll2 = |g: f32| {
        cmn()
            .tone_loglik(&std_g(), &creaky(g), &tone("2"), &c, &[])
            .unwrap()
    };
    assert!(ll2(9.0) < ll2(3.0) - 1.0);
    // Points inside the region but voiced (weight >= 0.5) still count.
    let mut voiced = creaky(9.0);
    voiced.voiced_weights[5] = 0.5;
    let with_voiced = cmn()
        .tone_loglik(&std_g(), &voiced, &tone("3"), &c, &[])
        .unwrap();
    assert!(with_voiced < ll3(9.0) - 1.0);
    // Points outside the region are never excused: k = 1 is u = 0.11.
    let mut outside = shape(vec![2., 1., 4.]);
    outside.voiced_weights[1] = 0.0;
    outside.contour[1] = 9.0;
    let clean = cmn()
        .tone_loglik(&std_g(), &shape(vec![2., 1., 4.]), &tone("3"), &c, &[])
        .unwrap();
    let hit = cmn()
        .tone_loglik(&std_g(), &outside, &tone("3"), &c, &[])
        .unwrap();
    assert!(hit < clean - 1.0);
}

#[test]
fn a_fully_excused_contour_falls_back_to_endpoints() {
    // Region [0, 1] for T3 and no voiced point: Σw = 0, so the contour term is dropped (no NaN).
    let toml = CMN_TOML.replace("region = [0.3, 0.8]", "region = [0.0, 1.0]");
    let pack = LanguagePack::from_toml(&toml, Some(CMN_CALIB)).unwrap();
    let mut x = shape(vec![2., 1., 4.]);
    x.voiced_weights = vec![0.0; CONTOUR_POINTS];
    let mut y = x.clone();
    y.contour[3] = 40.0;
    y.contour[6] = -7.0;
    let c = ctx(Some("1"), true);
    let jx = pack.judge(&std_g(), &x, &target("3"), &c, &[]).unwrap();
    let jy = pack.judge(&std_g(), &y, &target("3"), &c, &[]).unwrap();
    assert_all_finite(&jx);
    assert_all_finite(&jy);
    // T3's likelihood and distance see only the endpoints, so the garbage in between is invisible
    // to them (the other tones, with no region, still see it, so the llr itself moves).
    let ll3 = |s: &ToneShape| pack.tone_loglik(&std_g(), s, &tone("3"), &c, &[]).unwrap();
    assert_eq!(ll3(&x), ll3(&y));
    assert_eq!(jx.distance, jy.distance);
    assert!(jx.distance.unwrap() < 1e-3); // endpoints match [2,1,4]
    let ll1 = |s: &ToneShape| pack.tone_loglik(&std_g(), s, &tone("1"), &c, &[]).unwrap();
    assert!(ll1(&y) < ll1(&x));
}

#[test]
fn temperature_divides_every_loglik() {
    let hot = CMN_CALIB.replace("\"temperature\": 1.0", "\"temperature\": 2.5");
    assert_ne!(hot, CMN_CALIB);
    let hot = LanguagePack::from_toml(CMN_TOML, Some(&hot)).unwrap();
    let x = shape(vec![4., 2.]);
    let c = ctx(Some("1"), false);
    for t in ["1", "2", "3", "4", "5"] {
        let a = cmn().tone_loglik(&std_g(), &x, &tone(t), &c, &[]).unwrap();
        let b = hot.tone_loglik(&std_g(), &x, &tone(t), &c, &[]).unwrap();
        approx::assert_abs_diff_eq!(b, a / 2.5, epsilon = 1e-4);
    }
    let j = hot.judge(&std_g(), &x, &target("4"), &c, &[]).unwrap();
    let j1 = cmn().judge(&std_g(), &x, &target("4"), &c, &[]).unwrap();
    for (a, b) in j1.loglik.iter().zip(&j.loglik) {
        approx::assert_abs_diff_eq!(*b, a / 2.5, epsilon = 1e-4);
    }
    // The distance is uncalibrated.
    assert_eq!(j.distance, j1.distance);
}

// ---- judgement --------------------------------------------------------------------------

#[test]
fn judge_loglik_is_tone_loglik_per_inventory_tone() {
    let x = shape(vec![4., 2.]);
    let c = ctx(Some("3"), true);
    let pack = cmn();
    let issues = [MeasureIssue::ColdStartRegister];
    let j = pack.judge(&std_g(), &x, &target("2"), &c, &issues).unwrap();
    assert_eq!(j.expected, tone("2"));
    assert_eq!(j.loglik.len(), pack.inventory().len());
    for (t, ll) in pack.inventory().iter().zip(&j.loglik) {
        let direct = pack.tone_loglik(&std_g(), &x, t, &c, &issues).unwrap();
        assert_eq!(*ll, direct, "tone {t:?}");
    }
}

#[test]
fn llr_is_target_minus_prior_weighted_background() {
    // A single-component target with no variants: llr = ll_target − ln Σ prior_t·exp(ll_t).
    let pack = cmn();
    let x = shape(vec![4., 2.]);
    let c = ctx(Some("1"), false);
    let j = pack.judge(&std_g(), &x, &target("4"), &c, &[]).unwrap();
    let bg = pack
        .prior()
        .iter()
        .zip(&j.loglik)
        .map(|(p, l)| f64::from(*p) * f64::from(*l).exp())
        .sum::<f64>()
        .ln();
    let idx = pack
        .inventory()
        .iter()
        .position(|t| *t == tone("4"))
        .unwrap();
    approx::assert_abs_diff_eq!(
        f64::from(j.llr_target),
        f64::from(j.loglik[idx]) - bg,
        epsilon = 1e-4
    );
}

#[test]
fn heard_needs_the_pack_threshold() {
    let x = shape(vec![5., 1.]);
    let c = ctx(Some("1"), false);
    let j = cmn().judge(&std_g(), &x, &target("4"), &c, &[]).unwrap();
    assert_eq!(j.heard, Some(tone("4")));
    // The same evidence under a threshold no posterior can reach.
    let strict = CMN_TOML.replace("heard_threshold = 0.6", "heard_threshold = 1.0");
    let strict = LanguagePack::from_toml(&strict, Some(CMN_CALIB)).unwrap();
    let j = strict.judge(&std_g(), &x, &target("4"), &c, &[]).unwrap();
    assert_eq!(j.heard, None);
    // A shape midway between T1 [5,5] and T2 [3,5] is equally far from both (equal priors):
    // neither posterior reaches 0.6, so nothing is heard.
    let between = shape(vec![4., 5.]);
    let j = cmn()
        .judge(&std_g(), &between, &target("1"), &c, &[])
        .unwrap();
    assert_eq!(j.heard, None);
}

#[test]
fn heard_can_differ_from_expected() {
    let x = shape(vec![5., 1.]);
    let j = cmn()
        .judge(&std_g(), &x, &target("1"), &ctx(Some("1"), false), &[])
        .unwrap();
    assert_eq!(j.heard, Some(tone("4")));
    assert!(j.llr_target < 0.0);
}

#[test]
fn component_and_distance_name_the_best_realisation() {
    let c = ctx(Some("1"), true); // phrase-final T3 is a mixture: [2,1,4] 0.6, [2,1] 0.4
    let full = cmn()
        .judge(&std_g(), &shape(vec![2., 1., 4.]), &target("3"), &c, &[])
        .unwrap();
    assert_eq!(
        full.component.as_deref(),
        Some("cmn-standard/t3-final-dip#0")
    );
    assert!(full.distance.unwrap() < 0.05);
    let half = cmn()
        .judge(&std_g(), &shape(vec![2., 1.]), &target("3"), &c, &[])
        .unwrap();
    assert_eq!(
        half.component.as_deref(),
        Some("cmn-standard/t3-final-dip#1")
    );
    assert!(half.distance.unwrap() < 0.05);
    // An inherited rule keeps its owner's name when grading cmn-TW; a citation the graded one's.
    let tw = cmn()
        .judge(
            &g_for("cmn-TW"),
            &shape(vec![2., 1.]),
            &target("3"),
            &c,
            &[],
        )
        .unwrap();
    assert_eq!(tw.component.as_deref(), Some("cmn-TW/t3-low#0"));
    let t1 = cmn()
        .judge(
            &g_for("cmn-TW"),
            &shape(vec![5., 5.]),
            &target("1"),
            &c,
            &[],
        )
        .unwrap();
    assert_eq!(t1.component.as_deref(), Some("cmn-TW/citation"));
}

#[test]
fn lexical_variants_join_the_target_mixture() {
    // T4 with a 30% T1 variant: a level high syllable is far from T4 alone but not from the mix.
    let x = shape(vec![5., 5.]);
    let c = ctx(Some("1"), false);
    let plain = cmn().judge(&std_g(), &x, &target("4"), &c, &[]).unwrap();
    let mixed = cmn()
        .judge(&std_g(), &x, &target_with("4", &[("1", 0.3)]), &c, &[])
        .unwrap();
    assert!(mixed.llr_target > plain.llr_target + 1.0);
    assert!(plain.distance.unwrap() > 1.0);
    assert!(mixed.distance.unwrap() < 0.05); // best component is the T1 variant
                                             // ...and the clean main tone is barely hurt by the 0.3 given away: ln 0.7 at most.
    let t4 = shape(vec![5., 1.]);
    let solo = cmn().judge(&std_g(), &t4, &target("4"), &c, &[]).unwrap();
    let mix = cmn()
        .judge(&std_g(), &t4, &target_with("4", &[("1", 0.3)]), &c, &[])
        .unwrap();
    assert!(mix.llr_target < solo.llr_target);
    assert!(mix.llr_target > solo.llr_target + 0.7f32.ln() - 0.05);
    assert_eq!(mix.expected, tone("4"));
}

#[test]
fn measured_is_full_or_a_copy_of_the_issues() {
    let x = shape(vec![5., 1.]);
    let c = ctx(Some("1"), false);
    let j = cmn().judge(&std_g(), &x, &target("4"), &c, &[]).unwrap();
    assert_eq!(j.measured, Measured::Full);
    let issues = [MeasureIssue::Clipped, MeasureIssue::TooShort];
    let j = cmn()
        .judge(&std_g(), &x, &target("4"), &c, &issues)
        .unwrap();
    assert_eq!(
        j.measured,
        Measured::Partial {
            issues: issues.to_vec()
        }
    );
}

#[test]
fn errors_follow_the_pack_and_the_shape() {
    let x = shape(vec![5., 1.]);
    let c = ctx(Some("1"), false);
    let pack = cmn();
    assert!(matches!(
        pack.judge(&g_for("nope"), &x, &target("4"), &c, &[]),
        Err(PackError::UnknownAccent(_))
    ));
    assert!(matches!(
        pack.judge(&std_g(), &x, &target("9"), &c, &[]),
        Err(PackError::UnknownTone(_))
    ));
    assert!(matches!(
        pack.judge(&std_g(), &x, &target_with("4", &[("9", 0.1)]), &c, &[]),
        Err(PackError::UnknownTone(_))
    ));
    assert!(matches!(
        pack.judge(&std_g(), &x, &target("4"), &ctx(Some("9"), false), &[]),
        Err(PackError::UnknownTone(_))
    ));
    assert!(matches!(
        pack.tone_loglik(&std_g(), &x, &tone("9"), &c, &[]),
        Err(PackError::UnknownTone(_))
    ));
    assert!(matches!(
        pack.tone_loglik(&g_for("nope"), &x, &tone("1"), &c, &[]),
        Err(PackError::UnknownAccent(_))
    ));
    // A shape whose vectors are not CONTOUR_POINTS long is a caller bug, not a bad utterance.
    let mut short = x.clone();
    short.contour.pop();
    assert!(matches!(
        pack.judge(&std_g(), &short, &target("4"), &c, &[]),
        Err(PackError::Invalid(_))
    ));
    let mut weights = x.clone();
    weights.voiced_weights.truncate(3);
    assert!(matches!(
        pack.tone_loglik(&std_g(), &weights, &tone("4"), &c, &[]),
        Err(PackError::Invalid(_))
    ));
}

// ---- R12: everything finite -------------------------------------------------------------

#[test]
fn non_finite_shapes_give_finite_uninformative_output() {
    let c = ctx(Some("1"), false);
    let pack = cmn();
    let mut bad_shapes = Vec::new();
    for poison in [f32::NAN, f32::INFINITY, f32::NEG_INFINITY] {
        let mut a = shape(vec![5., 1.]);
        a.contour[4] = poison;
        bad_shapes.push(a);
        let mut b = shape(vec![5., 1.]);
        b.onset = poison;
        bad_shapes.push(b);
        let mut d = shape(vec![5., 1.]);
        d.offset = poison;
        bad_shapes.push(d);
        let mut e = shape(vec![5., 1.]);
        e.voiced_weights[2] = poison;
        bad_shapes.push(e);
    }
    for x in &bad_shapes {
        let j = pack.judge(&std_g(), x, &target("4"), &c, &[]).unwrap();
        assert_all_finite(&j);
        assert_eq!(j.llr_target, 0.0);
        assert!(j.loglik.iter().all(|v| *v == -1.0e6));
        assert_eq!(j.distance, None);
        assert_eq!(j.component, None);
        assert_eq!(j.heard, None);
        assert!(j.deltas.is_empty());
        assert_eq!(j.measured, Measured::Full);
        let ll = pack.tone_loglik(&std_g(), x, &tone("4"), &c, &[]).unwrap();
        assert_eq!(ll, -1.0e6);
    }
}

#[test]
fn absurd_finite_shapes_stay_finite_and_clamped() {
    let c = ctx(Some("1"), false);
    let pack = cmn();
    for scale in [1.0e3f32, 1.0e15, 1.0e30, 3.0e38] {
        let x = shape_from_contour(vec![scale; CONTOUR_POINTS]);
        for issues in [&[][..], &[MeasureIssue::TooShort], &[MeasureIssue::LowSnr]] {
            let j = pack.judge(&std_g(), &x, &target("4"), &c, issues).unwrap();
            assert_all_finite(&j);
        }
        let ll = pack.tone_loglik(&std_g(), &x, &tone("4"), &c, &[]).unwrap();
        assert!(ll.is_finite() && ll >= -1.0e6);
        // Opposite extremes in one contour, so onset/offset and range are huge and of both signs.
        let mut y = shape_from_contour(vec![-scale; CONTOUR_POINTS]);
        y.contour[9] = scale;
        y.offset = scale;
        assert_all_finite(&pack.judge(&std_g(), &y, &target("2"), &c, &[]).unwrap());
    }
    // A degenerate temperature cannot push a value past the clamp either.
    let tiny = CMN_CALIB.replace("\"temperature\": 1.0", "\"temperature\": 1e-30");
    let tiny = LanguagePack::from_toml(CMN_TOML, Some(&tiny)).unwrap();
    let x = shape(vec![3., 4.]);
    let j = tiny.judge(&std_g(), &x, &target("1"), &c, &[]).unwrap();
    assert_all_finite(&j);
    assert!(j.loglik.iter().any(|v| *v == -1.0e6));
}

// ---- deltas -----------------------------------------------------------------------------

fn deltas_of(
    knots: Vec<f32>,
    t: &str,
    c: &TargetContext,
    issues: &[MeasureIssue],
) -> Vec<(DeltaKind, f32)> {
    cmn()
        .judge(&std_g(), &shape(knots), &target(t), c, issues)
        .unwrap()
        .deltas
        .iter()
        .map(|d| (d.kind, d.amount))
        .collect()
}

#[test]
fn deltas_are_the_two_largest_above_one_sigma_in_chao_units() {
    // T1 [5,5] vs x [3,4]: onset z = −2/0.8 = −2.5, offset z = −1/0.8 = −1.25,
    // range z = (1 − 0)/0.7 = 1.43 (x is wider). The top two by |z|: onset, range.
    let d = deltas_of(vec![3., 4.], "1", &ctx(Some("1"), false), &[]);
    assert_eq!(d.len(), 2);
    assert_eq!(d[0].0, DeltaKind::StartHigher);
    approx::assert_abs_diff_eq!(d[0].1, 2.0, epsilon = 1e-4);
    assert_eq!(d[1].0, DeltaKind::NarrowerRange);
    approx::assert_abs_diff_eq!(d[1].1, 1.0, epsilon = 1e-4);
}

#[test]
fn onset_offset_and_range_deltas_in_every_direction() {
    let c = ctx(Some("1"), false);
    // T1 [5,5] vs [5,3]: offset low (z −2.5), range wider (2/0.7 = 2.86).
    let d = deltas_of(vec![5., 3.], "1", &c, &[]);
    assert_eq!(
        d.iter().map(|x| x.0).collect::<Vec<_>>(),
        [DeltaKind::NarrowerRange, DeltaKind::EndHigher]
    );
    approx::assert_abs_diff_eq!(d[1].1, 2.0, epsilon = 1e-4);
    // T1 [5,5] vs [5,7]: offset high.
    let d = deltas_of(vec![5., 7.], "1", &c, &[]);
    assert!(d.iter().any(|x| x.0 == DeltaKind::EndLower));
    // T2 [3,5] vs [5,5]: onset high (z 2.5); range narrower than the rising expectation.
    let d = deltas_of(vec![5., 5.], "2", &c, &[]);
    assert_eq!(
        d.iter().map(|x| x.0).collect::<Vec<_>>(),
        [DeltaKind::WiderRange, DeltaKind::StartLower]
    );
    approx::assert_abs_diff_eq!(d[0].1, 2.0, epsilon = 1e-4);
    approx::assert_abs_diff_eq!(d[1].1, 2.0, epsilon = 1e-4);
}

#[test]
fn a_clean_shape_has_no_deltas_and_one_sigma_is_the_threshold() {
    let c = ctx(Some("1"), false);
    assert!(deltas_of(vec![5., 5.], "1", &c, &[]).is_empty());
    // Onset 0.6 Chao low (z = −0.75; range z = 0.86): silent. 0.9 low (z = −1.125): speaks.
    assert!(deltas_of(vec![4.4, 5.], "1", &c, &[]).is_empty());
    assert!(deltas_of(vec![4.1, 5.], "1", &c, &[])
        .iter()
        .any(|d| d.0 == DeltaKind::StartHigher));
}

#[test]
fn turning_point_deltas_are_in_milliseconds() {
    let c = ctx(Some("1"), true);
    // The T3 dip [2,1,4] turns at u = 4/9. [2,2,1,4] turns at 6/9: late, so "turn earlier".
    let d = deltas_of(vec![2., 2., 1., 4.], "3", &c, &[]);
    assert_eq!(d.len(), 1, "{d:?}");
    assert_eq!(d[0].0, DeltaKind::TurnEarlier);
    approx::assert_abs_diff_eq!(d[0].1, (6.0 - 4.0) / 9.0 * 300.0, epsilon = 0.1);
    // [2,1,1.5,2,3,4] turns at 2/9: early, so "turn later".
    let d = deltas_of(vec![2., 1., 1.5, 2., 3., 4.], "3", &c, &[]);
    assert_eq!(d.len(), 1, "{d:?}");
    assert_eq!(d[0].0, DeltaKind::TurnLater);
    approx::assert_abs_diff_eq!(d[0].1, (4.0 - 2.0) / 9.0 * 300.0, epsilon = 0.1);
    // The amount scales with the syllable's duration.
    let mut x = shape(vec![2., 2., 1., 4.]);
    x.duration_ms = 150.0;
    let j = cmn().judge(&std_g(), &x, &target("3"), &c, &[]).unwrap();
    approx::assert_abs_diff_eq!(j.deltas[0].amount, (6.0 - 4.0) / 9.0 * 150.0, epsilon = 0.1);
    // Only when both have a turning point: a monotone fall against the dip says nothing about it.
    let d = deltas_of(vec![2., 1.], "3", &c, &[]);
    assert!(d
        .iter()
        .all(|x| !matches!(x.0, DeltaKind::TurnEarlier | DeltaKind::TurnLater)));
}

#[test]
fn deltas_are_suppressed_under_low_snr_only() {
    let c = ctx(Some("1"), false);
    assert!(!deltas_of(vec![3., 4.], "1", &c, &[]).is_empty());
    assert!(deltas_of(vec![3., 4.], "1", &c, &[MeasureIssue::LowSnr]).is_empty());
    assert!(deltas_of(
        vec![3., 4.],
        "1",
        &c,
        &[MeasureIssue::TooShort, MeasureIssue::LowSnr]
    )
    .is_empty());
    assert!(!deltas_of(vec![3., 4.], "1", &c, &[MeasureIssue::TooShort]).is_empty());
    assert!(!deltas_of(vec![3., 4.], "1", &c, &[MeasureIssue::Unvoiced]).is_empty());
    // Clipped and a cold register widen the tolerance, and with it the deltas' σ: an onset
    // 0.9 low is z = −1.125 normally but −0.75 when widened.
    assert!(!deltas_of(vec![4.1, 5.], "1", &c, &[]).is_empty());
    for issue in [MeasureIssue::Clipped, MeasureIssue::ColdStartRegister] {
        assert!(deltas_of(vec![4.1, 5.], "1", &c, &[issue]).is_empty());
    }
}

#[test]
fn too_short_gives_only_onset_and_offset_deltas() {
    // Ruling R26 (spec §12): a TooShort syllable is compared on onset/offset only, so it earns no
    // Turn* or Range deltas even when its turning point and range differ from the component's.
    //
    // Phrase-final T3, best component the full dip [2,1,4]. x has the dip's onset and offset but
    // turns late (u = 6/9 against 4/9: z = 1.11) and is wider (3.87 against 2.89: z = 1.40).
    let c = ctx(Some("1"), true);
    let knots = vec![2., 2., 2., -0.3, 1., 4.];
    let kinds = |x: &ToneShape, issues: &[MeasureIssue]| -> Vec<DeltaKind> {
        cmn()
            .judge(&std_g(), x, &target("3"), &c, issues)
            .unwrap()
            .deltas
            .iter()
            .map(|d| d.kind)
            .collect()
    };
    let x = shape(knots);
    assert!(x.turning_point.is_some());
    // Without the issue both contour-derived deltas speak (range first: larger |z|)...
    assert_eq!(
        kinds(&x, &[]),
        [DeltaKind::NarrowerRange, DeltaKind::TurnEarlier]
    );
    // ...with it, neither does; nothing else differs, so nothing at all is said.
    assert_eq!(kinds(&x, &[MeasureIssue::TooShort]), []);
    assert_eq!(
        kinds(&x, &[MeasureIssue::TooShort, MeasureIssue::Unvoiced]),
        []
    );

    // An onset mismatch still yields Start*, and only that, though the turning-point and range
    // differences are still there (they would be in the top two without TooShort).
    let set_onset = |v: f32| {
        let mut y = x.clone();
        y.onset = v;
        y.contour[0] = v;
        y
    };
    let low = set_onset(3.2); // 1.2 above the dip's 2: z = 1.5
    assert_eq!(
        kinds(&low, &[]),
        [DeltaKind::StartLower, DeltaKind::NarrowerRange]
    );
    let short = [MeasureIssue::TooShort];
    assert_eq!(kinds(&low, &short), [DeltaKind::StartLower]);
    let j = cmn()
        .judge(&std_g(), &low, &target("3"), &c, &short)
        .unwrap();
    approx::assert_abs_diff_eq!(j.deltas[0].amount, 1.2, epsilon = 1e-4);
    assert_eq!(kinds(&set_onset(0.4), &short), [DeltaKind::StartHigher]);

    // Offset likewise: EndHigher / EndLower survive.
    let mut y = x.clone();
    y.offset = 2.5; // 1.5 below the dip's 4, but still nearer it than the half-dip's 1
    assert_eq!(kinds(&y, &short), [DeltaKind::EndHigher]);
    y.offset = 6.0;
    assert_eq!(kinds(&y, &short), [DeltaKind::EndLower]);

    // Both endpoints off at once: the two deltas are the endpoint ones, largest |z| first.
    let mut z = set_onset(3.2);
    z.offset = 6.0; // z_off = 2/0.8 = 2.5 against z_on = 1.5
    assert_eq!(
        kinds(&z, &short),
        [DeltaKind::EndLower, DeltaKind::StartLower]
    );

    // Other issues alongside TooShort behave as before: Clipped widens the σ (onset 2.0 off:
    // z = 2/1.2 = 1.67) but keeps the restriction; LowSnr still suppresses everything.
    let far = set_onset(4.0);
    assert_eq!(
        kinds(&far, &[MeasureIssue::TooShort, MeasureIssue::Clipped]),
        [DeltaKind::StartLower]
    );
    assert!(kinds(&far, &[MeasureIssue::TooShort, MeasureIssue::LowSnr]).is_empty());

    // The brief's mismatch case: T1 [5,5] against [3,4] has onset, offset and range deltas
    // normally; under TooShort the onset and offset ones remain.
    let d = deltas_of(vec![3., 4.], "1", &ctx(Some("1"), false), &short);
    assert_eq!(
        d.iter().map(|d| d.0).collect::<Vec<_>>(),
        [DeltaKind::StartHigher, DeltaKind::EndHigher]
    );
}

#[test]
fn deltas_are_measured_against_the_best_component() {
    // Phrase-final T3 [2,1,4] 0.6 / [2,1] 0.4. A shape [2,1] is best matched by the half-dip,
    // so it draws no offset delta (it would against the full dip: offset 1 vs 4).
    let c = ctx(Some("1"), true);
    assert!(deltas_of(vec![2., 1.], "3", &c, &[]).is_empty());
    // A shape [2,1,4] against a target of tone 1 [5,5] (only one component) does draw them.
    assert!(!deltas_of(vec![2., 1., 4.], "1", &c, &[]).is_empty());
}

#[test]
fn deltas_with_non_finite_inputs_are_skipped_not_emitted() {
    let pack = cmn();
    // A NaN range: onset and offset still speak, the range delta is skipped.
    let c = ctx(Some("1"), false);
    let mut x = shape(vec![3., 4.]);
    x.range = f32::NAN;
    let j = pack.judge(&std_g(), &x, &target("1"), &c, &[]).unwrap();
    assert_all_finite(&j);
    assert!(j.deltas.iter().any(|d| d.kind == DeltaKind::StartHigher));
    assert!(j
        .deltas
        .iter()
        .all(|d| !matches!(d.kind, DeltaKind::WiderRange | DeltaKind::NarrowerRange)));
    // An infinite duration makes the turning-point amount infinite: the delta is skipped.
    let c = ctx(Some("1"), true);
    let mut x = shape(vec![2., 2., 1., 4.]);
    x.duration_ms = f32::INFINITY;
    let j = pack.judge(&std_g(), &x, &target("3"), &c, &[]).unwrap();
    assert_all_finite(&j);
    assert!(j.deltas.is_empty(), "{:?}", j.deltas);
    // A NaN turning point (or none at all) and a NaN duration.
    x.duration_ms = f32::NAN;
    x.turning_point = Some(f32::NAN);
    let j = pack.judge(&std_g(), &x, &target("3"), &c, &[]).unwrap();
    assert_all_finite(&j);
    assert!(j.deltas.is_empty(), "{:?}", j.deltas);
}
