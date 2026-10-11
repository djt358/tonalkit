mod common;

use approx::assert_abs_diff_eq;
use common::*;
use tonekit_core::{
    AccentId, F0Frame, F0Track, FrameRange, MeasureIssue, Register, TbuSpan, ToneId, ToneShape,
    CONTOUR_POINTS,
};
use tonekit_shape::*;
use tonekit_testkit::register_for;

// ---------------------------------------------------------------------------------------------
// The brief's tests.
// ---------------------------------------------------------------------------------------------

#[test]
fn level_high_maps_to_five() {
    let s = shape_of(vec![5., 5.], 100., 200., 300.);
    assert!(s.contour.iter().all(|c| (c - 5.0).abs() < 0.15));
}

#[test]
fn dipping_has_interior_turning_point() {
    let s = shape_of(vec![2., 1., 4.], 100., 200., 350.);
    let tp = s.turning_point.unwrap();
    assert!((tp - 0.5).abs() < 0.12 && s.curvature > 0.0);
}

#[test]
fn falling_has_negative_slope() {
    assert!(shape_of(vec![5., 1.], 100., 200., 300.).slope < 0.0);
}

#[test]
fn extreme_registers_normalize() {
    // Review Focus 1
    let lo = shape_of(vec![3., 5.], 75., 140., 300.);
    let hi = shape_of(vec![3., 5.], 180., 320., 300.);
    for k in 0..10 {
        assert!((lo.contour[k] - hi.contour[k]).abs() < 0.15);
    }
}

#[test]
fn short_syllable_partial() {
    // Review Focus 5
    let e = extract_of(vec![5., 1.], 70.);
    assert!(e.issues.contains(&MeasureIssue::TooShort));
}

#[test]
fn unvoiced_span_is_err() {
    let track = F0Track {
        frames: vec![
            F0Frame {
                hz: None,
                voiced_p: 0.0
            };
            60
        ],
        provider: "truth".to_string(),
    };
    let span = TbuSpan {
        start_frame: 10,
        end_frame: 40,
    };
    let err = extract(&track, &span, &register_for(100., 200.)).unwrap_err();
    assert_eq!(err, MeasureIssue::Unvoiced);
}

#[test]
fn cold_register_widens_and_merge_weights() {
    let r = cold_register(&[10.0, 12.0, 20.0], 3);
    assert!(r.floor_st < 10.0 && r.ceil_st > 20.0 && is_cold(&r));
    let m = merge_register(
        &Register {
            floor_st: 10.,
            median_st: 15.,
            ceil_st: 20.,
            n_syllables: 30,
        },
        &[12., 17., 22.],
        10,
    );
    approx::assert_abs_diff_eq!(m.n_syllables as f32, 40.0);
    assert!(m.ceil_st > 20.0 && m.ceil_st < 22.0);
}

// ---------------------------------------------------------------------------------------------
// style fitting
// ---------------------------------------------------------------------------------------------

fn shape_with(contour: Vec<f32>, range: f32) -> ToneShape {
    ToneShape {
        span: TbuSpan {
            start_frame: 0,
            end_frame: 30,
        },
        contour,
        voiced_weights: vec![1.0; CONTOUR_POINTS],
        onset: 0.0,
        offset: 0.0,
        mean: 0.0,
        slope: 0.0,
        curvature: 0.0,
        turning_point: None,
        range,
        duration_ms: 300.0,
        voiced_fraction: 1.0,
        f0_confidence: 1.0,
        phonation: None,
    }
}

fn tone(id: &str) -> ToneId {
    ToneId(id.to_string())
}

#[test]
fn style_fit_averages_per_tone() {
    let a: Vec<f32> = (0..CONTOUR_POINTS).map(|k| 2.0 + 0.2 * k as f32).collect();
    let b: Vec<f32> = (0..CONTOUR_POINTS).map(|k| 3.0 + 0.4 * k as f32).collect();
    let fits = vec![
        (tone("2"), shape_with(a.clone(), 1.8)),
        (tone("2"), shape_with(b.clone(), 3.6)),
    ];
    let p = fit_style(AccentId("cmn-standard".into()), &fits);
    assert_eq!(p.accent, AccentId("cmn-standard".into()));
    assert_eq!(p.tones.len(), 1);
    assert_eq!(p.tones[0].tone, tone("2"));
    assert_eq!(p.tones[0].n, 2);
    for k in 0..CONTOUR_POINTS {
        assert_abs_diff_eq!(p.tones[0].contour[k], 0.5 * (a[k] + b[k]), epsilon = 1e-6);
    }
    assert_abs_diff_eq!(p.mean_range, 2.7, epsilon = 1e-6);
}

#[test]
fn style_fit_keeps_first_seen_tone_order_and_counts() {
    let flat = |v: f32| vec![v; CONTOUR_POINTS];
    let fits = vec![
        (tone("3"), shape_with(flat(2.0), 1.0)),
        (tone("1"), shape_with(flat(5.0), 0.0)),
        (tone("3"), shape_with(flat(4.0), 2.0)),
        (tone("3"), shape_with(flat(3.0), 3.0)),
    ];
    let p = fit_style(AccentId("cmn-TW".into()), &fits);
    let ids: Vec<&str> = p.tones.iter().map(|t| t.tone.0.as_str()).collect();
    assert_eq!(ids, ["3", "1"]);
    assert_eq!((p.tones[0].n, p.tones[1].n), (3, 1));
    assert_abs_diff_eq!(p.tones[0].contour[0], 3.0, epsilon = 1e-6);
    assert_abs_diff_eq!(p.tones[1].contour[9], 5.0, epsilon = 1e-6);
    // mean_range is over all fits, not per tone: (1 + 0 + 2 + 3) / 4.
    assert_abs_diff_eq!(p.mean_range, 1.5, epsilon = 1e-6);
}

#[test]
fn style_fit_of_nothing_is_empty() {
    let p = fit_style(AccentId("cmn-standard".into()), &[]);
    assert!(p.tones.is_empty());
    assert_eq!(p.mean_range, 0.0);
}

// ---------------------------------------------------------------------------------------------
// Conversions and voiced frames
// ---------------------------------------------------------------------------------------------

#[test]
fn semitones_are_re_55_hz() {
    assert_abs_diff_eq!(hz_to_st(55.0), 0.0, epsilon = 1e-6);
    assert_abs_diff_eq!(hz_to_st(110.0), 12.0, epsilon = 1e-5);
    assert_abs_diff_eq!(hz_to_st(220.0), 24.0, epsilon = 1e-5);
    assert_abs_diff_eq!(hz_to_st(27.5), -12.0, epsilon = 1e-5);
}

#[test]
fn chao_is_linear_and_unclamped() {
    let r = Register {
        floor_st: 10.0,
        median_st: 14.0,
        ceil_st: 18.0,
        n_syllables: 100,
    };
    assert_abs_diff_eq!(st_to_chao(10.0, &r), 1.0, epsilon = 1e-6);
    assert_abs_diff_eq!(st_to_chao(14.0, &r), 3.0, epsilon = 1e-6);
    assert_abs_diff_eq!(st_to_chao(18.0, &r), 5.0, epsilon = 1e-6);
    assert_abs_diff_eq!(st_to_chao(20.0, &r), 6.0, epsilon = 1e-6);
    assert_abs_diff_eq!(st_to_chao(6.0, &r), -1.0, epsilon = 1e-6);
}

fn frame(hz: Option<f32>, voiced_p: f32) -> F0Frame {
    F0Frame { hz, voiced_p }
}

fn track(frames: Vec<F0Frame>) -> F0Track {
    F0Track {
        frames,
        provider: "test".to_string(),
    }
}

#[test]
fn voiced_semitones_needs_a_pitch_not_a_probability() {
    // R32: a frame is voiced when it has an f0, whatever its voiced_p.
    let t = track(vec![
        frame(Some(110.0), 1.0),  // voiced
        frame(None, 1.0),         // no f0: unvoiced however confident
        frame(Some(220.0), 0.49), // f0 at low confidence: voiced
        frame(Some(440.0), 0.0),  // f0 at zero confidence: voiced
        frame(Some(0.0), 0.9),    // not a pitch
        frame(Some(55.0), 0.9),   // voiced
    ]);
    let st = voiced_semitones(&t, None);
    assert_eq!(st.len(), 4);
    assert_abs_diff_eq!(st[0], 12.0, epsilon = 1e-5);
    assert_abs_diff_eq!(st[1], 24.0, epsilon = 1e-5);
    assert_abs_diff_eq!(st[2], 36.0, epsilon = 1e-5);
    assert_abs_diff_eq!(st[3], 0.0, epsilon = 1e-5);
}

#[test]
fn voiced_semitones_region_is_half_open_and_clamped() {
    let t = track(
        (0..10)
            .map(|i| frame(Some(55.0 * (1 + i) as f32), 1.0))
            .collect(),
    );
    let r = |start, end| Some(FrameRange { start, end });
    assert_eq!(voiced_semitones(&t, r(2, 5).as_ref()).len(), 3);
    assert_abs_diff_eq!(
        voiced_semitones(&t, r(1, 2).as_ref())[0],
        12.0,
        epsilon = 1e-5
    );
    assert_eq!(voiced_semitones(&t, r(8, 99).as_ref()).len(), 2);
    assert!(voiced_semitones(&t, r(50, 60).as_ref()).is_empty());
    assert!(voiced_semitones(&t, r(5, 5).as_ref()).is_empty());
    assert!(voiced_semitones(&t, r(6, 3).as_ref()).is_empty());
    assert_eq!(voiced_semitones(&t, None).len(), 10);
}

#[test]
fn speech_semitones_keep_only_voiced_frames_that_are_speech() {
    // R106: a pitch on a near-silent frame (a tracker at its floor between syllables) is not
    // the voice's, and frames past the end of the speech mask are not speech.
    let t = track(vec![
        frame(Some(110.0), 1.0), // speech: kept
        frame(Some(55.0), 0.3),  // not speech: left out
        frame(None, 1.0),        // speech, unvoiced: nothing
        frame(Some(220.0), 0.6), // speech: kept
        frame(Some(440.0), 1.0), // past the mask
    ]);
    let st = speech_semitones(&t, &[true, false, true, true]);
    assert_eq!(st.len(), 2);
    assert_abs_diff_eq!(st[0], 12.0, epsilon = 1e-5);
    assert_abs_diff_eq!(st[1], 24.0, epsilon = 1e-5);
    assert!(speech_semitones(&t, &[]).is_empty());
}

// ---------------------------------------------------------------------------------------------
// Register
// ---------------------------------------------------------------------------------------------

#[test]
fn cold_register_uses_interpolated_percentiles_plus_margin() {
    // 101 evenly spaced values 0..=100: p5 = 5, p50 = 50, p95 = 95 exactly.
    let st: Vec<f32> = (0..=100).map(|i| i as f32).collect();
    let r = cold_register(&st, 7);
    assert_abs_diff_eq!(r.floor_st, 3.0, epsilon = 1e-4);
    assert_abs_diff_eq!(r.median_st, 50.0, epsilon = 1e-4);
    assert_abs_diff_eq!(r.ceil_st, 97.0, epsilon = 1e-4);
    assert_eq!(r.n_syllables, 7);
    // The brief's three-point case: p5 = 10.2, p95 = 19.2 by linear interpolation.
    let r = cold_register(&[20.0, 10.0, 12.0], 3);
    assert_abs_diff_eq!(r.floor_st, 8.2, epsilon = 1e-4);
    assert_abs_diff_eq!(r.median_st, 12.0, epsilon = 1e-4);
    assert_abs_diff_eq!(r.ceil_st, 21.2, epsilon = 1e-4);
}

#[test]
fn cold_register_of_nothing_is_the_speaker_agnostic_default() {
    let r = cold_register(&[], 12);
    assert_abs_diff_eq!(r.floor_st, hz_to_st(90.0), epsilon = 1e-5);
    assert_abs_diff_eq!(r.median_st, hz_to_st(150.0), epsilon = 1e-5);
    assert_abs_diff_eq!(r.ceil_st, hz_to_st(250.0), epsilon = 1e-5);
    assert_eq!(r.n_syllables, 0);
    assert!(is_cold(&r));
}

#[test]
fn registers_keep_at_least_four_semitones() {
    // A monotone speaker: p5 = p50 = p95, so ±2 st is exactly the minimum.
    let r = cold_register(&[14.0; 20], 20);
    assert!(r.ceil_st - r.floor_st >= 4.0);
    assert_abs_diff_eq!(0.5 * (r.floor_st + r.ceil_st), 14.0, epsilon = 1e-4);
    // Merging a narrow utterance into a narrow register cannot shrink it below 4 st either.
    let narrow = Register {
        floor_st: 13.0,
        median_st: 14.0,
        ceil_st: 17.0,
        n_syllables: 5,
    };
    let m = merge_register(&narrow, &[15.0; 8], 8);
    assert!(m.ceil_st - m.floor_st >= 4.0);
    // A given register narrower than 4 st is widened symmetrically about its midpoint.
    let tiny = Register {
        floor_st: 14.0,
        median_st: 14.5,
        ceil_st: 15.0,
        n_syllables: 100,
    };
    let m = merge_register(&tiny, &[14.5; 4], 4);
    assert!(m.ceil_st - m.floor_st >= 4.0);
    assert_abs_diff_eq!(0.5 * (m.floor_st + m.ceil_st), 14.5, epsilon = 1e-3);
}

#[test]
fn merge_weight_is_capped_at_one_half() {
    let base = Register {
        floor_st: 10.0,
        median_st: 15.0,
        ceil_st: 20.0,
        n_syllables: 2,
    };
    // u/(n+u) = 8/10 → capped at 0.5. New utterance: p5 = 20, p50 = 25, p95 = 30 (constant).
    let m = merge_register(&base, &[20.0, 25.0, 30.0], 8);
    let (p5, p50, p95) = (20.5, 25.0, 29.5);
    assert_abs_diff_eq!(m.floor_st, 10.0 + 0.5 * (p5 - 10.0), epsilon = 1e-4);
    assert_abs_diff_eq!(m.median_st, 15.0 + 0.5 * (p50 - 15.0), epsilon = 1e-4);
    assert_abs_diff_eq!(m.ceil_st, 20.0 + 0.5 * (p95 - 20.0), epsilon = 1e-4);
    assert_eq!(m.n_syllables, 10);
}

#[test]
fn merge_of_nothing_only_counts_syllables() {
    let base = Register {
        floor_st: 10.0,
        median_st: 15.0,
        ceil_st: 20.0,
        n_syllables: 12,
    };
    let m = merge_register(&base, &[], 6);
    assert_eq!(
        m,
        Register {
            n_syllables: 18,
            ..base.clone()
        }
    );
    // A fresh register merging nothing stays where it is.
    let zero = Register {
        n_syllables: 0,
        ..base
    };
    assert_eq!(merge_register(&zero, &[], 0), zero);
}

#[test]
fn merge_into_an_empty_register_takes_half_the_new_values() {
    // n + u = 0 → w = 0.5 by decision.
    let zero = Register {
        floor_st: 0.0,
        median_st: 10.0,
        ceil_st: 20.0,
        n_syllables: 0,
    };
    let m = merge_register(&zero, &[30.0; 5], 0);
    assert_abs_diff_eq!(m.median_st, 20.0, epsilon = 1e-4);
    assert_eq!(m.n_syllables, 0);
}

#[test]
fn coldness_flips_at_thirty_syllables() {
    let r = |n| Register {
        floor_st: 0.0,
        median_st: 5.0,
        ceil_st: 10.0,
        n_syllables: n,
    };
    assert!(is_cold(&r(0)));
    assert!(is_cold(&r(29)));
    assert!(!is_cold(&r(30)));
    assert!(!is_cold(&r(400)));
}

// ---------------------------------------------------------------------------------------------
// Extraction
// ---------------------------------------------------------------------------------------------

#[test]
fn scalar_features_of_a_synthetic_syllable() {
    let e = extract_of(vec![5., 1.], 300.);
    let s = &e.shape;
    assert!(e.issues.is_empty());
    assert_eq!(s.contour.len(), CONTOUR_POINTS);
    assert_eq!(s.voiced_weights.len(), CONTOUR_POINTS);
    assert_eq!(s.phonation, None);
    assert_eq!(
        s.span,
        TbuSpan {
            start_frame: 20,
            end_frame: 50
        }
    );
    assert_eq!(s.duration_ms, 300.0);
    assert_abs_diff_eq!(s.voiced_fraction, 1.0);
    assert_abs_diff_eq!(s.f0_confidence, 1.0);
    // Onset and offset are the contour ends; range and mean are those of the contour.
    assert_eq!(s.onset, s.contour[0]);
    assert_eq!(s.offset, s.contour[CONTOUR_POINTS - 1]);
    let (min, max) = s
        .contour
        .iter()
        .fold((f32::MAX, f32::MIN), |(lo, hi), &c| (lo.min(c), hi.max(c)));
    assert_abs_diff_eq!(s.range, max - min, epsilon = 1e-6);
    let mean = s.contour.iter().sum::<f32>() / CONTOUR_POINTS as f32;
    assert_abs_diff_eq!(s.mean, mean, epsilon = 1e-5);
    // A 5→1 fall across 300 ms is about −4/0.3 Chao per second, a bit shallower because the
    // voiced part ends one frame before the truth does.
    assert!(s.slope < -12.0 && s.slope > -15.0, "slope {}", s.slope);
    assert!(s.range > 3.5);
    assert!(s.voiced_weights.iter().all(|&w| w == 1.0));
}

#[test]
fn slope_is_per_second_and_signed() {
    let up = shape_of(vec![1., 5.], 100., 200., 400.);
    let down = shape_of(vec![5., 1.], 100., 200., 400.);
    assert!(up.slope > 9.0 && up.slope < 11.0, "slope {}", up.slope);
    assert_abs_diff_eq!(up.slope, -down.slope, epsilon = 0.05);
    assert_abs_diff_eq!(
        shape_of(vec![3., 3.], 100., 200., 300.).slope,
        0.0,
        epsilon = 0.05
    );
}

#[test]
fn level_tone_has_no_turning_point_and_no_curvature() {
    let s = shape_of(vec![3., 3.], 100., 200., 300.);
    assert_eq!(s.turning_point, None);
    assert_abs_diff_eq!(s.curvature, 0.0, epsilon = 0.05);
    assert_abs_diff_eq!(s.range, 0.0, epsilon = 0.05);
}

#[test]
fn monotone_contours_have_no_turning_point() {
    for chao in [
        vec![1., 5.],
        vec![5., 1.],
        vec![2., 3., 5.],
        vec![5., 3., 1.],
    ] {
        let s = shape_of(chao.clone(), 100., 200., 320.);
        assert_eq!(s.turning_point, None, "{chao:?}");
    }
}

#[test]
fn peak_is_a_turning_point_and_curves_downwards() {
    let s = shape_of(vec![2., 5., 2.], 100., 200., 400.);
    let tp = s.turning_point.expect("interior maximum");
    assert!((tp - 0.5).abs() < 0.1, "tp {tp}");
    assert!(s.curvature < 0.0);
}

#[test]
fn turning_point_needs_half_a_chao_beyond_both_endpoints() {
    // Dip of 0.3 Chao below the lower endpoint: not reported.
    let shallow = shape_of(vec![3., 2.7, 3.], 100., 200., 400.);
    assert_eq!(shallow.turning_point, None);
    // 1.0 below both endpoints: reported.
    assert!(shape_of(vec![3., 2., 3.], 100., 200., 400.)
        .turning_point
        .is_some());
    // A dip that is deep relative to one endpoint but only 0.3 below the other is not reported.
    assert_eq!(
        shape_of(vec![3., 2.7, 4.5], 100., 200., 400.).turning_point,
        None
    );
}

#[test]
fn turning_point_must_be_interior() {
    // A dip to Chao 1 at u = 0.04 (knot 1 of 26), then a steady climb to 5: the minimum is real
    // but inside the excluded first 10 % of the voiced part.
    let mut early = vec![3.0_f32];
    early.extend((0..25).map(|i| 1.0 + 4.0 * i as f32 / 24.0));
    assert_eq!(
        shape_of(early.clone(), 100., 200., 400.).turning_point,
        None
    );
    // The mirror image: a fall to 1 and a jump back at the very end.
    let late: Vec<f32> = early.into_iter().rev().collect();
    assert_eq!(shape_of(late, 100., 200., 400.).turning_point, None);
}

#[test]
fn turning_point_takes_the_larger_excursion_when_both_qualify() {
    // W-ish: a shallow dip (to 2 from 3) at ~0.25 and a tall peak (to 5) at ~0.75.
    let s = shape_of(vec![3., 2., 3., 5., 3.], 100., 200., 500.);
    let tp = s.turning_point.expect("a turning point");
    assert!((tp - 0.75).abs() < 0.1, "peak wins: tp {tp}");
    // Swap which is larger: a deep dip (to 1) and a small bump (to 4).
    let s = shape_of(vec![3., 1., 3., 4., 3.], 100., 200., 500.);
    let tp = s.turning_point.expect("a turning point");
    assert!((tp - 0.25).abs() < 0.1, "dip wins: tp {tp}");
}

#[test]
fn a_creaky_middle_is_interpolated_and_lowers_the_voiced_weights() {
    // A 40-frame voiced part (frames 10..50) whose middle 10 frames are unvoiced, on a straight
    // 2→4 line.
    let (floor, ceil) = (100.0_f32, 200.0_f32);
    let reg = register_for(floor, ceil);
    let chao_of = |j: usize| 2.0 + 2.0 * j as f32 / 39.0;
    let frames: Vec<F0Frame> = (0..60)
        .map(|i| {
            if !(10..50).contains(&i) || (25..35).contains(&i) {
                return F0Frame {
                    hz: None,
                    voiced_p: 0.0,
                };
            }
            F0Frame {
                hz: Some(tonekit_testkit::chao_to_hz(chao_of(i - 10), floor, ceil)),
                voiced_p: 1.0,
            }
        })
        .collect();
    let t = F0Track {
        frames,
        provider: "truth".into(),
    };
    let span = TbuSpan {
        start_frame: 5,
        end_frame: 55,
    };
    let e = extract(&t, &span, &reg).unwrap();
    let s = e.shape;
    // The contour still runs straight through the hole...
    for (k, c) in s.contour.iter().enumerate() {
        let want = 2.0 + 2.0 * k as f32 / 9.0;
        assert!((c - want).abs() < 0.12, "point {k}: {c} vs {want}");
    }
    // ...but the points in the hole say so.
    assert!(s.voiced_weights[0] == 1.0 && s.voiced_weights[9] == 1.0);
    assert!(s.voiced_weights[4] < 0.5 || s.voiced_weights[5] < 0.5);
    assert!(s.voiced_weights.iter().all(|w| (0.0..=1.0).contains(w)));
    assert!(s.voiced_weights.contains(&0.0));
    // 30 voiced frames of a 50-frame span.
    assert_abs_diff_eq!(s.voiced_fraction, 0.6, epsilon = 1e-6);
    assert_eq!(s.duration_ms, 500.0);
    // The voiced part (frames 10..50, holes included) is 400 ms: long enough, no issue.
    assert!(e.issues.is_empty());
}

#[test]
fn edge_unvoiced_frames_are_not_part_of_the_voiced_part() {
    // Voicing only in frames 20..30 of a span 0..50: the contour covers exactly that.
    let (floor, ceil) = (100.0_f32, 200.0_f32);
    let frames: Vec<F0Frame> = (0..60)
        .map(|i| {
            if (20..30).contains(&i) {
                F0Frame {
                    hz: Some(tonekit_testkit::chao_to_hz(
                        1.0 + (i - 20) as f32 * 4.0 / 9.0,
                        floor,
                        ceil,
                    )),
                    voiced_p: 0.9,
                }
            } else {
                F0Frame {
                    hz: None,
                    voiced_p: 0.0,
                }
            }
        })
        .collect();
    let t = F0Track {
        frames,
        provider: "x".into(),
    };
    let e = extract(
        &t,
        &TbuSpan {
            start_frame: 0,
            end_frame: 50,
        },
        &register_for(floor, ceil),
    )
    .unwrap();
    assert_abs_diff_eq!(e.shape.contour[0], 1.0, epsilon = 0.05);
    assert_abs_diff_eq!(e.shape.contour[9], 5.0, epsilon = 0.05);
    assert_abs_diff_eq!(e.shape.voiced_fraction, 0.2, epsilon = 1e-6);
    assert_abs_diff_eq!(e.shape.f0_confidence, 0.9, epsilon = 1e-6);
    assert!(e.shape.voiced_weights.iter().all(|&w| w == 1.0));
}

#[test]
fn too_short_is_exactly_below_eighty_milliseconds_of_voiced_part() {
    let run = |n: u32| {
        let frames: Vec<F0Frame> = (0..40)
            .map(|i| {
                if (10..10 + n).contains(&i) {
                    F0Frame {
                        hz: Some(150.0),
                        voiced_p: 1.0,
                    }
                } else {
                    F0Frame {
                        hz: None,
                        voiced_p: 0.0,
                    }
                }
            })
            .collect();
        let t = F0Track {
            frames,
            provider: "x".into(),
        };
        extract(
            &t,
            &TbuSpan {
                start_frame: 0,
                end_frame: 40,
            },
            &register_for(100., 200.),
        )
        .unwrap()
    };
    assert_eq!(run(7).issues, vec![MeasureIssue::TooShort]);
    assert!(run(8).issues.is_empty());
    // The shape is still returned when too short (onset/offset terms are still usable).
    assert_eq!(run(3).shape.contour.len(), CONTOUR_POINTS);
    assert_eq!(run(3).issues, vec![MeasureIssue::TooShort]);
}

#[test]
fn a_gap_inside_the_voiced_part_counts_towards_its_duration() {
    // Two 4-frame islands 6 frames apart: the voiced part is 14 frames = 140 ms.
    let frames: Vec<F0Frame> = (0..40)
        .map(|i| {
            if (10..14).contains(&i) || (20..24).contains(&i) {
                F0Frame {
                    hz: Some(150.0),
                    voiced_p: 1.0,
                }
            } else {
                F0Frame {
                    hz: None,
                    voiced_p: 0.0,
                }
            }
        })
        .collect();
    let t = F0Track {
        frames,
        provider: "x".into(),
    };
    let e = extract(
        &t,
        &TbuSpan {
            start_frame: 0,
            end_frame: 40,
        },
        &register_for(100., 200.),
    )
    .unwrap();
    assert!(e.issues.is_empty());
    assert_abs_diff_eq!(e.shape.voiced_fraction, 8.0 / 40.0, epsilon = 1e-6);
}

#[test]
fn fewer_than_three_voiced_frames_is_unvoiced() {
    let mk = |voiced: &[usize]| {
        let frames: Vec<F0Frame> = (0..30)
            .map(|i| {
                if voiced.contains(&i) {
                    F0Frame {
                        hz: Some(150.0),
                        voiced_p: 1.0,
                    }
                } else {
                    F0Frame {
                        hz: None,
                        voiced_p: 0.0,
                    }
                }
            })
            .collect();
        let t = F0Track {
            frames,
            provider: "x".into(),
        };
        extract(
            &t,
            &TbuSpan {
                start_frame: 0,
                end_frame: 30,
            },
            &register_for(100., 200.),
        )
    };
    assert_eq!(mk(&[]).unwrap_err(), MeasureIssue::Unvoiced);
    assert_eq!(mk(&[5]).unwrap_err(), MeasureIssue::Unvoiced);
    assert_eq!(mk(&[5, 20]).unwrap_err(), MeasureIssue::Unvoiced);
    assert!(mk(&[5, 12, 20]).is_ok());
}

#[test]
fn low_voicing_probability_is_confidence_not_voicing() {
    // R32: f0 present with voiced_p 0.3 everywhere is voiced (pYIN's own decision); the low
    // probability only lowers f0_confidence. Before R32 this span was Unvoiced.
    let frames: Vec<F0Frame> = (0..30)
        .map(|_| F0Frame {
            hz: Some(150.0),
            voiced_p: 0.3,
        })
        .collect();
    let t = F0Track {
        frames,
        provider: "x".into(),
    };
    let e = extract(
        &t,
        &TbuSpan {
            start_frame: 0,
            end_frame: 30,
        },
        &register_for(100., 200.),
    )
    .unwrap();
    assert!(e.issues.is_empty());
    assert_abs_diff_eq!(e.shape.voiced_fraction, 1.0, epsilon = 1e-6);
    assert!(e.shape.voiced_weights.iter().all(|&w| w == 1.0));
    assert_abs_diff_eq!(e.shape.f0_confidence, 0.3, epsilon = 1e-6);
    let level = st_to_chao(hz_to_st(150.0), &register_for(100., 200.));
    assert!(e.shape.contour.iter().all(|&c| (c - level).abs() < 1e-4));
}

#[test]
fn degenerate_spans_are_unvoiced_not_panics() {
    let c = case(vec![3., 3.], 100., 200., 300.);
    let e = |start_frame, end_frame| {
        extract(
            &c.f0,
            &TbuSpan {
                start_frame,
                end_frame,
            },
            &c.register,
        )
    };
    assert_eq!(e(30, 30).unwrap_err(), MeasureIssue::Unvoiced);
    assert_eq!(e(40, 30).unwrap_err(), MeasureIssue::Unvoiced);
    assert_eq!(e(10_000, 10_010).unwrap_err(), MeasureIssue::Unvoiced);
    // A span running past the end of the track is clamped to it.
    assert!(e(20, 10_000).is_ok());
}

#[test]
fn non_positive_or_non_finite_hz_never_yields_nan() {
    let mut c = case(vec![3., 4.], 100., 200., 300.);
    c.f0.frames[30].hz = Some(0.0);
    c.f0.frames[31].hz = Some(f32::NAN);
    c.f0.frames[32].hz = Some(-5.0);
    let s = extract_case(&c).shape;
    assert!(s.contour.iter().all(|x| x.is_finite()));
    assert!(s.slope.is_finite() && s.curvature.is_finite() && s.mean.is_finite());
    assert!(s.voiced_fraction < 1.0);
}

#[test]
fn extraction_is_deterministic() {
    let a = extract_of(vec![2., 1., 4.], 350.);
    let b = extract_of(vec![2., 1., 4.], 350.);
    assert_eq!(a, b);
}

// ---------------------------------------------------------------------------------------------
// Real pYIN (ruling R32): a voiced frame is `hz.is_some()`.
// ---------------------------------------------------------------------------------------------

#[test]
fn the_initial_fall_of_spoken_4_1_3_reads_as_a_fall_on_real_pyin() {
    use tonekit_f0::{repair_octaves, F0Provider, Pyin};
    use tonekit_testkit::{synth, SynthSpec, SynthSyllable};
    // Task 9's spoken(4-1-3): three 250 ms syllables [5,1], [5,5], [2,1,4] with 60 ms gaps. pYIN
    // tracks the first syllable's fall to within a few Hz but with voiced_p mostly below 0.5.
    // Before R32 only 4 of its 25 frames counted as voiced (one of them octave-doubled by the old
    // repair) and it read as a dip-rise, about [4.4 ... 3.0 ... 6.0].
    let spec = SynthSpec {
        floor_hz: 100.0,
        ceil_hz: 200.0,
        lead_ms: 200.0,
        tail_ms: 200.0,
        syllables: [vec![5.0, 1.0], vec![5.0, 5.0], vec![2.0, 1.0, 4.0]]
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
    };
    let s = synth(&spec);
    let mut f0 = Pyin::default().track(&s.pcm);
    repair_octaves(&mut f0);
    let (start_frame, end_frame) = s.syllable_frames[0];
    let e = extract(
        &f0,
        &TbuSpan {
            start_frame,
            end_frame,
        },
        &register_for(100.0, 200.0),
    )
    .expect("the fall is voiced");
    let c = &e.shape.contour;
    assert!(e.issues.is_empty(), "{e:?}");
    assert!(e.shape.voiced_fraction > 0.9, "{e:?}");
    assert!(e.shape.voiced_weights.iter().all(|&w| w == 1.0), "{e:?}");
    // A clean fall from near Chao 5 to near Chao 1, never rising by more than R23's jitter.
    assert!(c[0] > 4.5 && c[9] < 1.5, "{c:?}");
    assert!(c.windows(2).all(|w| w[1] < w[0] + 0.15), "{c:?}");
    assert!(
        e.shape.slope < 0.0 && e.shape.turning_point.is_none(),
        "{e:?}"
    );
}

// ---------------------------------------------------------------------------------------------
// Ruling R50: a nucleus's shape comes from its own voiced run.
// ---------------------------------------------------------------------------------------------

/// A 60-frame track voiced (at `hz(i)`, `voiced_p` 0.8) exactly on the frames `voiced(i)` holds.
fn track_where(voiced: impl Fn(u32) -> bool, hz: impl Fn(u32) -> f32) -> F0Track {
    F0Track {
        frames: (0..60)
            .map(|i| F0Frame {
                hz: voiced(i).then(|| hz(i)),
                voiced_p: if voiced(i) { 0.8 } else { 0.0 },
            })
            .collect(),
        provider: "x".into(),
    }
}

fn span(start_frame: u32, end_frame: u32) -> TbuSpan {
    TbuSpan {
        start_frame,
        end_frame,
    }
}

#[test]
fn a_nucleus_shape_ignores_voiced_frames_outside_its_own_run() {
    // A level syllable at Chao 3 on frames 20..40, and three frames of high "bleed" at 43..46 after a
    // three-frame hole: the bleed is a run of its own and plays no part.
    let reg = register_for(100.0, 200.0);
    let hz = |i: u32| {
        let chao = if i < 42 { 3.0 } else { 5.0 };
        tonekit_testkit::chao_to_hz(chao, 100.0, 200.0)
    };
    let with_bleed = track_where(|i| (20..40).contains(&i) || (43..46).contains(&i), hz);
    let alone = track_where(|i| (20..40).contains(&i), hz);
    let got = extract_nucleus(&with_bleed, &span(15, 50), 30, &reg, Joins::NONE).unwrap();
    let want = extract(&alone, &span(15, 50), &reg).unwrap();
    assert_eq!(got, want);
    // Whereas the whole span's first..last voiced frame bends up into the bleed.
    let whole = extract(&with_bleed, &span(15, 50), &reg).unwrap();
    assert!(whole.shape.contour[9] > 4.0, "{whole:?}");
    assert!((got.shape.contour[9] - 3.0).abs() < 0.05, "{got:?}");
    // The span is the one asked for, and so are the fractions over it.
    assert_eq!(got.shape.span, span(15, 50));
    assert_eq!(got.shape.duration_ms, 350.0);
    assert_abs_diff_eq!(got.shape.voiced_fraction, 20.0 / 35.0, epsilon = 1e-6);
}

#[test]
fn a_run_bridges_holes_of_up_to_two_frames() {
    let reg = register_for(100.0, 200.0);
    let hz = |_| 150.0;
    // Frames 20..30 and 32..40 (a two-frame hole): one run, so a nucleus in either half sees both.
    let two = track_where(|i| (20..30).contains(&i) || (32..40).contains(&i), hz);
    for nucleus in [22, 30, 36] {
        let e = extract_nucleus(&two, &span(10, 50), nucleus, &reg, Joins::NONE).unwrap();
        assert_eq!(e, extract(&two, &span(10, 50), &reg).unwrap(), "{nucleus}");
    }
    // A three-frame hole (20..30, 33..40) with the pitch breaking across it (150 → 190 Hz, 4.1
    // semitones) ends the run: each half is its own.
    let three = track_where(
        |i| (20..30).contains(&i) || (33..40).contains(&i),
        |i| if i < 31 { 150.0 } else { 190.0 },
    );
    let left = extract_nucleus(&three, &span(10, 50), 25, &reg, Joins::NONE).unwrap();
    let right = extract_nucleus(&three, &span(10, 50), 35, &reg, Joins::NONE).unwrap();
    assert_abs_diff_eq!(left.shape.voiced_fraction, 10.0 / 40.0, epsilon = 1e-6);
    assert_abs_diff_eq!(right.shape.voiced_fraction, 7.0 / 40.0, epsilon = 1e-6);
}

#[test]
fn a_dropout_inside_one_contour_is_filled_not_cut() {
    // Ruling R58: a creaky tone 3, falling from Chao 2 to 1 on 20..30, 6 unvoiced frames at the
    // bottom, rising from Chao 1.2 to 4 on 36..50. The pitch moves under 3 semitones across the
    // hole, so from either side the voiced part is the whole contour, hole filled and weighted.
    let reg = register_for(100.0, 200.0);
    let chao = |i: u32| match i {
        0..=29 => 2.0 - (i as f32 - 20.0) / 10.0,
        _ => 1.2 + (i as f32 - 36.0) * 2.8 / 13.0,
    };
    let creaky = track_where(
        |i| (20..30).contains(&i) || (36..50).contains(&i),
        |i| tonekit_testkit::chao_to_hz(chao(i), 100.0, 200.0),
    );
    let whole = extract(&creaky, &span(15, 55), &reg).unwrap();
    for nucleus in [24, 32, 44] {
        let e = extract_nucleus(&creaky, &span(15, 55), nucleus, &reg, Joins::NONE).unwrap();
        assert_eq!(e, whole, "{nucleus}");
    }
    assert!(
        whole.shape.onset > 1.8 && whole.shape.offset > 3.8,
        "{whole:?}"
    );
    assert!(
        whole.shape.voiced_weights.iter().any(|&w| w < 0.5),
        "{whole:?}"
    );
}

#[test]
fn a_nucleus_between_runs_takes_the_nearest() {
    // Runs at 10..20 (150 Hz) and 30..45 (190 Hz, a pitch break); a nucleus at 23 is 4 frames
    // from the first and 7 from the second.
    let reg = register_for(100.0, 200.0);
    let t = track_where(
        |i| (10..20).contains(&i) || (30..45).contains(&i),
        |i| if i < 25 { 150.0 } else { 190.0 },
    );
    let e = extract_nucleus(&t, &span(5, 50), 23, &reg, Joins::NONE).unwrap();
    assert_abs_diff_eq!(e.shape.voiced_fraction, 10.0 / 45.0, epsilon = 1e-6);
    let e = extract_nucleus(&t, &span(5, 50), 27, &reg, Joins::NONE).unwrap();
    assert_abs_diff_eq!(e.shape.voiced_fraction, 15.0 / 45.0, epsilon = 1e-6);
    // Only voiced frames inside the span count: a run cut by the span edge is what is left of it.
    let e = extract_nucleus(&t, &span(15, 50), 12, &reg, Joins::NONE).unwrap();
    assert_abs_diff_eq!(e.shape.voiced_fraction, 5.0 / 35.0, epsilon = 1e-6);
}

#[test]
fn a_nucleus_run_too_short_for_a_shape_is_unvoiced() {
    // The nucleus's run has two voiced frames; the span's other run would have given a shape.
    let reg = register_for(100.0, 200.0);
    let t = track_where(
        |i| (10..12).contains(&i) || (30..45).contains(&i),
        |_| 150.0,
    );
    assert_eq!(
        extract_nucleus(&t, &span(5, 50), 11, &reg, Joins::NONE),
        Err(MeasureIssue::Unvoiced)
    );
    assert!(extract(&t, &span(5, 50), &reg).is_ok());
    let silent = track_where(|_| false, |_| 150.0);
    assert_eq!(
        extract_nucleus(&silent, &span(5, 50), 20, &reg, Joins::NONE),
        Err(MeasureIssue::Unvoiced)
    );
    assert_eq!(
        extract_nucleus(&t, &span(40, 40), 40, &reg, Joins::NONE),
        Err(MeasureIssue::Unvoiced)
    );
}

#[test]
fn too_short_is_judged_on_the_voiced_part_left_after_trimming_joins() {
    // Fix round 1, item 5: TooShort says the contour's interior is too short to trust, so it is
    // judged on the frames the shape is measured on. A fully voiced 100 ms TBU is long enough
    // untrimmed; joined at both edges it loses 2 frames each side (a quarter of 10 is 2) and its
    // 60 ms voiced part is TooShort.
    let reg = register_for(100.0, 200.0);
    let t = track_where(|i| (20..30).contains(&i), |_| 150.0);
    let both = Joins {
        start: true,
        end: true,
    };
    let plain = extract_nucleus(&t, &span(20, 30), 25, &reg, Joins::NONE).unwrap();
    assert!(!plain.issues.contains(&MeasureIssue::TooShort), "{plain:?}");
    let joined = extract_nucleus(&t, &span(20, 30), 25, &reg, both).unwrap();
    assert!(
        joined.issues.contains(&MeasureIssue::TooShort),
        "{joined:?}"
    );
}

#[test]
fn a_join_edge_leaves_out_the_transition_frames_beside_it() {
    // Ruling R61. One run from 10 to 50: a glide down from Chao 5 on 10..13, Chao 3 on 13..47,
    // a glide up on 47..50. Marked as joins, the glides are left out of the voiced part; the span
    // and the fractions over it are still the whole span's.
    let reg = register_for(100.0, 200.0);
    let chao = |i: u32| match i {
        10..=12 => 5.0 - (i - 10 + 1) as f32 * 0.5,
        47..=49 => 3.0 + (i - 46) as f32 * 0.5,
        _ => 3.0,
    };
    let t = track_where(
        |i| (10..50).contains(&i),
        |i| tonekit_testkit::chao_to_hz(chao(i), 100.0, 200.0),
    );
    let both = Joins {
        start: true,
        end: true,
    };
    let joined = extract_nucleus(&t, &span(10, 50), 30, &reg, both).unwrap();
    assert!(
        joined.shape.contour.iter().all(|c| (c - 3.0).abs() < 0.01),
        "{joined:?}"
    );
    assert_eq!(joined.shape.span, span(10, 50));
    assert_abs_diff_eq!(joined.shape.voiced_fraction, 34.0 / 40.0, epsilon = 1e-6);
    // Unmarked, the glides bend both ends.
    let plain = extract_nucleus(&t, &span(10, 50), 30, &reg, Joins::NONE).unwrap();
    assert!(
        plain.shape.onset > 4.0 && plain.shape.offset > 4.0,
        "{plain:?}"
    );
}
