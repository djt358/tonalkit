use std::f64::consts::PI;

use approx::{assert_abs_diff_eq, assert_relative_eq};
use tonekit_testkit::*;

// ---------------------------------------------------------------------------------------------
// The brief's three tests, verbatim.
// ---------------------------------------------------------------------------------------------

fn one(chao: Vec<f32>) -> SynthSpec {
    SynthSpec {
        floor_hz: 100.0,
        ceil_hz: 200.0,
        lead_ms: 200.0,
        tail_ms: 200.0,
        snr_db: None,
        seed: 7,
        syllables: vec![SynthSyllable {
            chao,
            dur_ms: 300.0,
            gap_after_ms: 0.0,
            unvoiced_onset_ms: 0.0,
            creak: None,
        }],
    }
}
#[test]
fn level_tone_truth_is_ceiling() {
    let s = synth(&one(vec![5.0, 5.0]));
    let (a, b) = s.syllable_frames[0];
    for i in a + 3..b - 3 {
        approx::assert_relative_eq!(s.f0_truth[i as usize].unwrap(), 200.0, max_relative = 0.01);
    }
}
#[test]
fn deterministic_and_sized() {
    let (x, y) = (synth(&one(vec![3.0, 5.0])), synth(&one(vec![3.0, 5.0])));
    assert_eq!(x.pcm, y.pcm);
    assert_eq!(x.pcm.len(), 16 * 700);
    assert_eq!(x.f0_truth.len(), x.pcm.len() / 160 + 1);
}
#[test]
fn gaps_are_unvoiced() {
    let s = synth(&one(vec![5.0, 1.0]));
    assert!(s.f0_truth[..15].iter().all(|f| f.is_none()));
}

// ---------------------------------------------------------------------------------------------
// Helpers.
//
// Layout used by most tests: 200 ms lead (samples 0..3200), one 300 ms syllable (samples
// 3200..8000, frames 20..50), 200 ms tail (samples 8000..11200).
// ---------------------------------------------------------------------------------------------

const VS: usize = 3200;
const VE: usize = 8000;

fn syl(chao: Vec<f32>, dur_ms: f32, gap_after_ms: f32, onset_ms: f32) -> SynthSyllable {
    SynthSyllable {
        chao,
        dur_ms,
        gap_after_ms,
        unvoiced_onset_ms: onset_ms,
        creak: None,
    }
}

fn spec_with(syllables: Vec<SynthSyllable>, snr_db: Option<f32>, seed: u64) -> SynthSpec {
    SynthSpec {
        floor_hz: 100.0,
        ceil_hz: 200.0,
        lead_ms: 200.0,
        tail_ms: 200.0,
        snr_db,
        seed,
        syllables,
    }
}

fn one_syl(s: SynthSyllable) -> SynthSpec {
    spec_with(vec![s], None, 7)
}

fn rms(x: &[f32]) -> f64 {
    (x.iter().map(|v| f64::from(*v).powi(2)).sum::<f64>() / x.len() as f64).sqrt()
}

fn peak(x: &[f32]) -> f32 {
    x.iter().fold(0.0_f32, |m, v| m.max(v.abs()))
}

/// Amplitude of the sinusoid component of `x` at `freq_hz` (exact when the window holds a whole
/// number of periods).
fn dft_amp(x: &[f32], freq_hz: f64) -> f64 {
    let (mut re, mut im) = (0.0, 0.0);
    for (n, v) in x.iter().enumerate() {
        let w = 2.0 * PI * freq_hz * n as f64 / 16_000.0;
        re += f64::from(*v) * w.cos();
        im += f64::from(*v) * w.sin();
    }
    2.0 * (re * re + im * im).sqrt() / x.len() as f64
}

fn st(hz: f64) -> f64 {
    12.0 * (hz / 55.0).log2()
}

// ---------------------------------------------------------------------------------------------
// Chao map and register.
// ---------------------------------------------------------------------------------------------

#[test]
fn chao_to_hz_hits_floor_and_ceil_and_interpolates_in_semitones() {
    assert_relative_eq!(chao_to_hz(1.0, 100.0, 200.0), 100.0, max_relative = 1e-5);
    assert_relative_eq!(chao_to_hz(5.0, 100.0, 200.0), 200.0, max_relative = 1e-5);
    // Chao 3 is the semitone midpoint, i.e. the geometric (not arithmetic) mean of the endpoints.
    assert_relative_eq!(
        chao_to_hz(3.0, 100.0, 200.0),
        (100.0_f32 * 200.0).sqrt(),
        max_relative = 1e-5
    );
    // Unclamped: one Chao step is a quarter of the floor..ceil span, so chao 9 is one span above.
    assert_relative_eq!(chao_to_hz(9.0, 100.0, 200.0), 400.0, max_relative = 1e-5);
    assert_relative_eq!(chao_to_hz(-3.0, 100.0, 200.0), 50.0, max_relative = 1e-5);
}

#[test]
fn chao_to_hz_is_the_exact_inverse_of_the_shape_crate_chao_map() {
    let (floor_hz, ceil_hz) = (95.0_f32, 260.0_f32);
    let (floor_st, ceil_st) = (st(f64::from(floor_hz)), st(f64::from(ceil_hz)));
    for chao in [0.0_f32, 1.0, 1.7, 2.5, 3.0, 4.2, 5.0, 6.5] {
        let hz = chao_to_hz(chao, floor_hz, ceil_hz);
        // Chao = 1 + 4·(st − floor_st)/(ceil_st − floor_st), unclamped.
        let back = 1.0 + 4.0 * (st(f64::from(hz)) - floor_st) / (ceil_st - floor_st);
        assert_abs_diff_eq!(back, f64::from(chao), epsilon = 1e-3);
    }
}

#[test]
fn register_for_is_in_semitones_re_55_and_not_cold() {
    let r = register_for(100.0, 200.0);
    assert_abs_diff_eq!(f64::from(r.floor_st), st(100.0), epsilon = 1e-4);
    assert_abs_diff_eq!(f64::from(r.ceil_st), st(200.0), epsilon = 1e-4);
    // An octave is 12 semitones.
    assert_abs_diff_eq!(r.ceil_st - r.floor_st, 12.0, epsilon = 1e-4);
    assert_eq!(r.median_st, 0.5 * (r.floor_st + r.ceil_st));
    assert_eq!(r.n_syllables, 100);
    // 55 Hz is 0 st.
    assert_abs_diff_eq!(register_for(55.0, 110.0).floor_st, 0.0, epsilon = 1e-6);
}

// ---------------------------------------------------------------------------------------------
// f0 ground truth.
// ---------------------------------------------------------------------------------------------

#[test]
fn voiced_frames_are_exactly_the_voiced_part() {
    let s = synth(&one(vec![3.0, 3.0]));
    assert_eq!(s.syllable_frames, vec![(20, 50)]);
    assert_eq!(s.f0_truth.len(), 11_200 / 160 + 1);
    assert!(s.f0_truth[..20].iter().all(Option::is_none));
    assert!(s.f0_truth[20..50].iter().all(Option::is_some));
    assert!(s.f0_truth[50..].iter().all(Option::is_none));
}

#[test]
fn f0_truth_follows_chao_knots_evenly_spaced_and_linear_in_chao() {
    // Three knots sit at u = 0, 0.5, 1 of the voiced part; chao is linear between them.
    let s = synth(&one(vec![2.0, 4.0, 3.0]));
    let nv = (VE - VS) as f64;
    for frame in 20..50_usize {
        let u = (frame * 160 - VS) as f64 / (nv - 1.0);
        let chao = if u <= 0.5 {
            2.0 + 2.0 * (u / 0.5)
        } else {
            4.0 - (u - 0.5) / 0.5
        };
        let want = chao_to_hz(chao as f32, 100.0, 200.0);
        assert_relative_eq!(s.f0_truth[frame].unwrap(), want, max_relative = 1e-4);
    }
    // A rising tone starts on the floor and climbs towards (but, sampled every 10 ms, stops one
    // hop short of) the ceiling: frame 49 is at u = 4640/4799.
    let r = synth(&one(vec![1.0, 5.0]));
    let rising: Vec<f32> = r.f0_truth[20..50].iter().map(|f| f.unwrap()).collect();
    assert_relative_eq!(rising[0], 100.0, max_relative = 1e-4);
    assert!(rising.windows(2).all(|w| w[1] > w[0]));
    let last = chao_to_hz((1.0 + 4.0 * 4640.0 / 4799.0) as f32, 100.0, 200.0);
    assert_relative_eq!(rising[29], last, max_relative = 1e-4);
    assert!(rising[29] < 200.0 && rising[29] > 190.0);
}

#[test]
fn single_knot_contour_is_level() {
    let s = synth(&one(vec![3.0]));
    let want = chao_to_hz(3.0, 100.0, 200.0);
    for frame in 20..50 {
        assert_relative_eq!(s.f0_truth[frame].unwrap(), want, max_relative = 1e-5);
    }
}

#[test]
fn multi_syllable_frames_gaps_and_length() {
    // A: 200..455 ms, gap 45. B: 500..700 ms (50 ms whispered onset), gap 100. Tail 105.
    let s = synth(&spec_with_tail(
        vec![
            syl(vec![3.0, 3.0], 255.0, 45.0, 0.0),
            syl(vec![4.0, 4.0], 200.0, 100.0, 50.0),
        ],
        105.0,
    ));
    // 455 ms is frame 45.5 and rounds half away from zero.
    assert_eq!(s.syllable_frames, vec![(20, 46), (50, 70)]);
    assert_eq!(s.pcm.len(), 905 * 16);
    assert_eq!(s.f0_truth.len(), 905 * 16 / 160 + 1);
    let is_some = |r: std::ops::Range<usize>| s.f0_truth[r].iter().all(Option::is_some);
    let is_none = |r: std::ops::Range<usize>| s.f0_truth[r].iter().all(Option::is_none);
    assert!(is_none(0..20));
    assert!(is_some(20..46)); // A voiced
    assert!(is_none(46..50)); // A gap
    assert!(is_none(50..55)); // B onset noise
    assert!(is_some(55..70)); // B voiced
    assert!(is_none(70..91)); // gap and tail
                              // The gap between A and B is exact silence (no SNR noise here).
    assert!(s.pcm[455 * 16..500 * 16].iter().all(|x| *x == 0.0));
}

fn spec_with_tail(syllables: Vec<SynthSyllable>, tail_ms: f32) -> SynthSpec {
    SynthSpec {
        tail_ms,
        ..spec_with(syllables, None, 7)
    }
}

#[test]
fn no_syllables_is_silence_of_lead_plus_tail() {
    let s = synth(&spec_with(vec![], None, 1));
    assert_eq!(s.pcm.len(), 400 * 16);
    assert!(s.pcm.iter().all(|x| *x == 0.0));
    assert!(s.syllable_frames.is_empty());
    assert_eq!(s.f0_truth.len(), 6400 / 160 + 1);
    assert!(s.f0_truth.iter().all(Option::is_none));
}

#[test]
fn empty_timeline_still_has_one_frame() {
    let s = synth(&SynthSpec {
        lead_ms: 0.0,
        tail_ms: 0.0,
        ..spec_with(vec![], None, 1)
    });
    assert!(s.pcm.is_empty());
    assert_eq!(s.f0_truth, vec![None]);
}

#[test]
#[should_panic(expected = "chao")]
fn voiced_syllable_without_chao_knots_is_rejected() {
    let _ = synth(&one(vec![]));
}

// ---------------------------------------------------------------------------------------------
// Waveform: harmonics, envelope, normalisation.
// ---------------------------------------------------------------------------------------------

#[test]
fn harmonics_are_one_over_h_and_stop_below_4_khz() {
    // f0 = 16000/90 Hz, so a 90-sample period and 4000/f0 = 22.5: harmonics 1..=22 exist, 23 does
    // not. A window of 40 whole periods makes the DFT bins exact.
    let f0 = 16_000.0 / 90.0;
    let mut spec = one(vec![5.0, 5.0]);
    spec.ceil_hz = f0 as f32;
    let s = synth(&spec);
    let win = &s.pcm[3600..3600 + 3600]; // inside the flat part of the envelope
    let a1 = dft_amp(win, f0);
    for h in [2_u32, 3, 7, 22] {
        assert_relative_eq!(
            dft_amp(win, f64::from(h) * f0) / a1,
            1.0 / f64::from(h),
            max_relative = 0.01
        );
    }
    for h in [23_u32, 30, 60] {
        assert!(dft_amp(win, f64::from(h) * f0) / a1 < 1e-3, "harmonic {h}");
    }
    // Nothing between the harmonics either.
    assert!(dft_amp(win, 1.5 * f0) / a1 < 1e-3);
}

#[test]
fn a_pitch_near_zero_still_renders() {
    // A Chao value far below the floor is a pitch of almost 0 Hz, which once asked for endless
    // harmonics: the harmonic count is bounded as if f0 were at least 1 Hz.
    let s = synth(&one_syl(syl(vec![-1.0e6], 20.0, 0.0, 0.0)));
    assert_eq!(s.pcm.len(), 16 * 420);
    assert!(s.pcm.iter().all(|x| x.is_finite()));
}

#[test]
fn phase_is_accumulated_from_the_instantaneous_f0() {
    // One positive-going zero crossing per cycle of the 1/h harmonic sum, so the crossing count
    // over a gliding pitch must equal ∫f0 dt.
    let s = synth(&one(vec![1.0, 5.0]));
    let nv = (VE - VS) as f64;
    let (lo, hi) = (VS + 400, VE - 400);
    let crossings = s.pcm[lo - 1..hi]
        .windows(2)
        .filter(|w| w[0] < 0.0 && w[1] >= 0.0)
        .count();
    let cycles: f64 = (lo..hi)
        .map(|n| {
            let u = (n - VS) as f64 / (nv - 1.0);
            f64::from(chao_to_hz((1.0 + 4.0 * u) as f32, 100.0, 200.0)) / 16_000.0
        })
        .sum();
    assert!(
        (crossings as f64 - cycles).abs() <= 1.0,
        "{crossings} crossings vs {cycles:.2} cycles"
    );
}

#[test]
fn voiced_part_has_raised_cosine_ramps_at_both_edges() {
    let s = synth(&one(vec![5.0, 5.0]));
    assert!(s.pcm[VS].abs() < 1e-6);
    assert!(s.pcm[VE - 1].abs() < 1e-6);
    // 5 ms into a 20 ms raised-cosine ramp the gain is 0.146, so the normalised peak is < 0.073.
    assert!(peak(&s.pcm[VS..VS + 80]) < 0.1);
    assert!(peak(&s.pcm[VE - 80..VE]) < 0.1);
    // Full amplitude once the ramps are over.
    assert!(peak(&s.pcm[4000..4400]) > 0.4);
}

#[test]
fn ramps_shrink_to_fit_a_very_short_voiced_part() {
    let mut spec = one(vec![3.0, 3.0]);
    spec.syllables[0].dur_ms = 30.0; // shorter than two 20 ms ramps
    let s = synth(&spec);
    assert_eq!(s.pcm.len(), (200 + 30 + 200) * 16);
    assert!(s.pcm.iter().all(|x| x.is_finite()));
    assert_abs_diff_eq!(peak(&s.pcm), 0.5, epsilon = 1e-6);
}

#[test]
fn peak_is_normalised_to_one_half() {
    let mut creaky = one(vec![3.0, 5.0]);
    creaky.syllables[0].creak = Some((0.3, 0.5));
    for spec in [
        one(vec![3.0, 5.0]),
        one(vec![1.0, 1.0]),
        creaky,
        spec_with(vec![syl(vec![3.0, 3.0], 300.0, 0.0, 100.0)], Some(15.0), 3),
        spec_with(vec![syl(vec![3.0], 300.0, 0.0, 300.0)], None, 3), // whispered
    ] {
        assert_abs_diff_eq!(peak(&synth(&spec).pcm), 0.5, epsilon = 1e-6);
    }
}

// ---------------------------------------------------------------------------------------------
// Unvoiced onset, whisper, creak.
// ---------------------------------------------------------------------------------------------

#[test]
fn unvoiced_onset_is_noise_at_a_tenth_of_the_voiced_peak() {
    let s = synth(&one_syl(syl(vec![3.0, 3.0], 300.0, 0.0, 100.0)));
    assert_eq!(s.syllable_frames, vec![(20, 50)]); // onset counts towards the syllable
    assert!(s.f0_truth[20..30].iter().all(Option::is_none));
    assert!(s.f0_truth[30..50].iter().all(Option::is_some));
    // Voiced peak is normalised to 0.5, so the noise sigma is 0.05 (1600 samples: ~2% error).
    let onset_rms = rms(&s.pcm[VS..VS + 1600]);
    assert!((0.045..0.055).contains(&onset_rms), "onset rms {onset_rms}");
    // Voiced part starts after the onset: the ramp starts from zero there.
    assert!(s.pcm[VS + 1600].abs() < 1e-6);
}

#[test]
fn fully_whispered_syllable_is_noise_with_no_f0() {
    let s = synth(&one_syl(syl(vec![3.0, 3.0], 300.0, 0.0, 300.0)));
    assert_eq!(s.syllable_frames, vec![(20, 50)]);
    assert!(s.f0_truth.iter().all(Option::is_none));
    assert!(rms(&s.pcm[VS..VE]) > 0.05);
    // Outside the syllable it is still silent.
    assert!(s.pcm[..VS].iter().all(|x| *x == 0.0));
    assert!(s.pcm[VE..].iter().all(|x| *x == 0.0));
    assert_abs_diff_eq!(peak(&s.pcm), 0.5, epsilon = 1e-6);
}

#[test]
fn onset_longer_than_the_syllable_is_treated_as_whispered() {
    let s = synth(&one_syl(syl(vec![3.0, 3.0], 300.0, 0.0, 999.0)));
    assert_eq!(s.pcm.len(), 11_200);
    assert!(s.f0_truth.iter().all(Option::is_none));
}

fn creaky(range: (f32, f32)) -> SynthSpec {
    let mut spec = one(vec![3.0, 5.0]);
    spec.syllables[0].creak = Some(range);
    spec
}

#[test]
fn creak_range_has_no_f0_and_low_level_noise() {
    // Voiced part is samples 3200..8000; 0.4..0.6 of it is samples 5120..6080 = frames 32..38.
    let s = synth(&creaky((0.4, 0.6)));
    assert_eq!(s.syllable_frames, vec![(20, 50)]);
    assert!(s.f0_truth[..20].iter().all(Option::is_none));
    assert!(s.f0_truth[20..32].iter().all(Option::is_some));
    assert!(s.f0_truth[32..38].iter().all(Option::is_none));
    assert!(s.f0_truth[38..50].iter().all(Option::is_some));
    assert!(s.f0_truth[50..].iter().all(Option::is_none));
    // Noise sigma is 0.05 of the (0.5) voiced peak = 0.025; 960 samples: ~2.3% error.
    let creak_rms = rms(&s.pcm[5120..6080]);
    assert!((0.022..0.028).contains(&creak_rms), "creak rms {creak_rms}");
    // Voiced neighbours are far louder.
    assert!(rms(&s.pcm[4000..5000]) > 5.0 * creak_rms);
}

#[test]
fn creak_leaves_the_pitch_of_the_rest_of_the_syllable_on_the_contour() {
    let plain = synth(&one(vec![3.0, 5.0]));
    let creak = synth(&creaky((0.4, 0.6)));
    for frame in (20..32).chain(38..50) {
        assert_eq!(plain.f0_truth[frame], creak.f0_truth[frame]);
    }
}

#[test]
fn creak_covering_the_whole_voiced_part_leaves_no_f0() {
    let s = synth(&creaky((0.0, 1.0)));
    assert!(s.f0_truth.iter().all(Option::is_none));
}

#[test]
fn empty_or_inverted_creak_range_changes_nothing() {
    let plain = synth(&one(vec![3.0, 5.0]));
    assert_eq!(synth(&creaky((0.5, 0.5))), plain);
    assert_eq!(synth(&creaky((0.7, 0.2))), plain);
}

// ---------------------------------------------------------------------------------------------
// RNG use: seeds and SNR noise.
// ---------------------------------------------------------------------------------------------

#[test]
fn seed_matters_only_when_noise_is_drawn() {
    let clean = |seed| {
        synth(&spec_with(
            vec![syl(vec![3.0, 3.0], 300.0, 0.0, 0.0)],
            None,
            seed,
        ))
    };
    assert_eq!(clean(1).pcm, clean(2).pcm);

    let onset = |seed| {
        synth(&spec_with(
            vec![syl(vec![3.0, 3.0], 300.0, 0.0, 100.0)],
            None,
            seed,
        ))
    };
    assert_eq!(onset(5), onset(5));
    assert_ne!(onset(5).pcm, onset(6).pcm);
    assert_eq!(onset(5).f0_truth, onset(6).f0_truth);
}

#[test]
fn seed_zero_is_valid_and_deterministic() {
    let spec = spec_with(vec![syl(vec![3.0, 3.0], 300.0, 0.0, 100.0)], Some(20.0), 0);
    let (a, b) = (synth(&spec), synth(&spec));
    assert_eq!(a, b);
    assert!(rms(&a.pcm[..VS]) > 0.0);
}

#[test]
fn snr_noise_is_deterministic_per_seed_and_does_not_touch_truth() {
    let noisy = |seed, snr| {
        synth(&spec_with(
            vec![syl(vec![3.0, 5.0], 300.0, 0.0, 0.0)],
            snr,
            seed,
        ))
    };
    let a = noisy(11, Some(20.0));
    assert_eq!(a, noisy(11, Some(20.0)));
    assert_ne!(a.pcm, noisy(12, Some(20.0)).pcm);
    let clean = noisy(11, None);
    assert_ne!(a.pcm, clean.pcm);
    assert_eq!(a.f0_truth, clean.f0_truth);
    assert_eq!(a.syllable_frames, clean.syllable_frames);
    // The noise covers the whole buffer, lead and tail included.
    assert!(a.pcm[..VS].iter().any(|x| *x != 0.0));
    assert!(a.pcm[VE..].iter().any(|x| *x != 0.0));
}

#[test]
fn snr_sets_noise_rms_relative_to_voiced_rms() {
    for snr in [10.0_f32, 20.0, 30.0] {
        let s = synth(&spec_with(
            vec![syl(vec![3.0, 3.0], 300.0, 0.0, 0.0)],
            Some(snr),
            21,
        ));
        // The lead is pure noise (rms N); the voiced part is signal S plus noise N.
        let noise = rms(&s.pcm[..VS]);
        let voiced = rms(&s.pcm[VS..VE]);
        let want = (1.0 + 10.0_f64.powf(f64::from(snr) / 10.0)).sqrt();
        assert_relative_eq!(voiced / noise, want, max_relative = 0.06);
    }
}
