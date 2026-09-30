mod common;

use common::*;
use proptest::prelude::*;
use tonekit_core::Register;
use tonekit_shape::{cold_register, extract, merge_register};

/// Contours whose slope stays at or below 2 Chao per unit of normalised time: the time-stretch
/// test below is limited by frame quantisation (see `time_stretch_invariance`), and steeper
/// flanks, such as a 3 → 1 → 3 dip, exceed its ±0.1 tolerance without anything being wrong.
const CONTOURS: [&[f32]; 6] = [
    &[3., 3.],
    &[5., 5.],
    &[3., 5.],
    &[2., 4.],
    &[5., 3.],
    &[3.5, 2.5, 3.5],
];

/// Every contour the tests use, the steep ones included.
const ALL_CONTOURS: [&[f32]; 8] = [
    &[3., 3.],
    &[5., 5.],
    &[3., 5.],
    &[2., 4.],
    &[5., 3.],
    &[3.5, 2.5, 3.5],
    &[5., 1.],
    &[2., 1., 4.],
];

proptest! {
    #[test]
    fn pitch_scale_invariance(k in 0.7f32..1.4, which in 0usize..6) {
        let c = case(CONTOURS[which].to_vec(), 100., 200., 300.);
        let base = extract_case(&c).shape;

        // Everyone's pitch is multiplied by k: every hz, and with it the register.
        let shift = 12.0 * k.log2();
        let mut scaled = case(CONTOURS[which].to_vec(), 100., 200., 300.);
        for f in &mut scaled.f0.frames {
            f.hz = f.hz.map(|hz| hz * k);
        }
        scaled.register = Register {
            floor_st: c.register.floor_st + shift,
            median_st: c.register.median_st + shift,
            ceil_st: c.register.ceil_st + shift,
            n_syllables: c.register.n_syllables,
        };
        let got = extract(&scaled.f0, &scaled.span, &scaled.register).unwrap().shape;
        for i in 0..base.contour.len() {
            prop_assert!(
                (base.contour[i] - got.contour[i]).abs() <= 0.05,
                "point {}: {} vs {}", i, base.contour[i], got.contour[i]
            );
        }
    }

    /// A syllable stretched in time keeps its contour, to the precision the 10 ms frame grid
    /// allows: the voiced part ends up to one hop before the truth does, so a contour point can
    /// move by up to (hop / duration) × the local slope in Chao per unit of normalised time
    /// (≈ 0.033 × slope at 300 ms, ≈ 0.047 × slope at 210 ms).
    #[test]
    fn time_stretch_invariance(f in 0.7f32..1.4, which in 0usize..6) {
        let base = shape_of(CONTOURS[which].to_vec(), 100., 200., 300.);
        let got = shape_of(CONTOURS[which].to_vec(), 100., 200., 300. * f);
        for i in 0..base.contour.len() {
            prop_assert!(
                (base.contour[i] - got.contour[i]).abs() <= 0.1,
                "point {}: {} vs {}", i, base.contour[i], got.contour[i]
            );
        }
    }

    /// The same, for every contour including the steep ones the test above leaves out. The frame
    /// grid moves a contour point by up to (hop / duration) × the local slope in Chao per unit of
    /// normalised time, so the honest tolerance grows with the steepest flank: measured worst
    /// cases over 0.7 ≤ f ≤ 1.4 are 0.036 × that slope (0.072 for a 3 → 5 rise, 0.144 for a 5 → 1
    /// fall, 0.217 for a 2 → 1 → 4 dip); 0.045 × slope leaves a quarter of headroom.
    #[test]
    fn time_stretch_error_is_bounded_by_the_frame_grid(f in 0.7f32..1.4, which in 0usize..8) {
        let contour = ALL_CONTOURS[which];
        let steepest = contour
            .windows(2)
            .map(|w| (w[1] - w[0]).abs() * (contour.len() - 1) as f32)
            .fold(0.0_f32, f32::max);
        let base = shape_of(contour.to_vec(), 100., 200., 300.);
        let got = shape_of(contour.to_vec(), 100., 200., 300. * f);
        for i in 0..base.contour.len() {
            prop_assert!(
                (base.contour[i] - got.contour[i]).abs() <= 0.045 * steepest,
                "point {}: {} vs {} (steepest flank {})", i, base.contour[i], got.contour[i], steepest
            );
        }
    }

    /// Whatever the pitch, contours sit where the register says: a level tone at Chao c stays at c.
    #[test]
    fn level_tones_read_back_their_chao(c in 1.0f32..5.0, floor in 70.0f32..200.0, ratio in 1.5f32..2.5) {
        let s = shape_of(vec![c, c], floor, floor * ratio, 300.);
        prop_assert!(s.contour.iter().all(|x| (x - c).abs() < 0.1));
        prop_assert!(s.turning_point.is_none());
    }

    /// The floor-to-ceiling distance is at least 4 st, exactly, however the f32 rounding falls.
    #[test]
    fn registers_are_never_narrower_than_four_semitones(
        base in -5.0f32..60.0,
        spread in 0.0f32..3.0,
        count in 1usize..40,
        prior_floor in -5.0f32..60.0,
        prior_width in 0.0f32..8.0,
        prior_n in 0u32..100,
        syllables in 0u32..50,
    ) {
        let st: Vec<f32> = (0..count)
            .map(|i| base + spread * i as f32 / count as f32)
            .collect();

        let cold = cold_register(&st, syllables);
        prop_assert!(cold.ceil_st - cold.floor_st >= 4.0, "cold {:?}", cold);
        prop_assert!(cold.floor_st <= cold.median_st && cold.median_st <= cold.ceil_st);

        let prior = Register {
            floor_st: prior_floor,
            median_st: prior_floor + 0.5 * prior_width,
            ceil_st: prior_floor + prior_width,
            n_syllables: prior_n,
        };
        let merged = merge_register(&prior, &st, syllables);
        prop_assert!(merged.ceil_st - merged.floor_st >= 4.0, "merged {:?} from {:?}", merged, prior);
        prop_assert!(merged.floor_st <= merged.median_st && merged.median_st <= merged.ceil_st);
        prop_assert_eq!(merged.n_syllables, prior_n + syllables);
    }
}
