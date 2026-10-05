//! `synth_fluent`: contiguous syllables with glides, dips and optional fricative onsets.
//!
//! Layout used by most tests: 200 ms lead (samples 0..3200), three 200 ms syllables (samples
//! 3200..6400, 6400..9600, 9600..12800; frames 20..40, 40..60, 60..80), 200 ms tail.

use approx::assert_relative_eq;
use tonekit_testkit::*;

const JOIN: usize = 6400;

fn syl(chao: Vec<f32>) -> FluentSyllable {
    FluentSyllable::at_rate(chao, 5.0)
}

fn spec(syllables: Vec<FluentSyllable>, glide_ms: f32, dip_db: f32) -> FluentSpec {
    FluentSpec {
        floor_hz: 100.0,
        ceil_hz: 200.0,
        lead_ms: 200.0,
        tail_ms: 200.0,
        syllables,
        glide_ms,
        dip_db,
        dip_ms: 80.0,
        snr_db: None,
        seed: 3,
    }
}

fn levels(glide_ms: f32, dip_db: f32) -> FluentSpec {
    spec(
        vec![syl(vec![5.0]), syl(vec![1.0]), syl(vec![3.0])],
        glide_ms,
        dip_db,
    )
}

fn rms(x: &[f32]) -> f64 {
    (x.iter().map(|&v| f64::from(v).powi(2)).sum::<f64>() / x.len() as f64).sqrt()
}

/// Level in dB of the 10 ms around sample `at`.
fn level_db(pcm: &[f32], at: usize) -> f64 {
    20.0 * rms(&pcm[at - 80..at + 80]).log10()
}

#[test]
fn at_rate_sets_the_length_and_no_onset() {
    let s = FluentSyllable::at_rate(vec![5.0, 1.0], 4.0);
    assert_eq!(s.dur_ms, 250.0);
    assert_eq!(s.unvoiced_onset_ms, 0.0);
}

#[test]
fn deterministic_sized_and_contiguous() {
    let (x, y) = (
        synth_fluent(&levels(40.0, 6.0)),
        synth_fluent(&levels(40.0, 6.0)),
    );
    assert_eq!(x, y);
    assert_eq!(x.pcm.len(), 16 * 1000);
    assert_eq!(x.f0_truth.len(), x.pcm.len() / 160 + 1);
    assert_eq!(x.syllable_frames, vec![(20, 40), (40, 60), (60, 80)]);
    let peak = x.pcm.iter().fold(0.0_f32, |m, v| m.max(v.abs()));
    assert_relative_eq!(peak, 0.5, max_relative = 1e-6);
}

#[test]
fn voicing_runs_on_across_voiced_joins() {
    let s = synth_fluent(&levels(40.0, 12.0));
    assert!(s.f0_truth[..20].iter().all(Option::is_none));
    assert!(s.f0_truth[20..80].iter().all(Option::is_some));
    assert!(s.f0_truth[81..].iter().all(Option::is_none));
}

#[test]
fn outside_the_glides_each_syllable_keeps_its_own_contour() {
    let s = synth_fluent(&levels(40.0, 6.0));
    for (frames, chao) in [(21..37, 5.0), (43..57, 1.0), (63..80, 3.0)] {
        for i in frames {
            assert_relative_eq!(
                s.f0_truth[i].unwrap(),
                chao_to_hz(chao, 100.0, 200.0),
                max_relative = 1e-5
            );
        }
    }
}

#[test]
fn a_glide_is_a_raised_cosine_in_semitones_centred_on_the_join() {
    let s = synth_fluent(&levels(40.0, 0.0));
    // Chao 5 → 1: the join is halfway in semitones (Chao 3), and the glide is monotonic.
    assert_relative_eq!(
        s.f0_truth[JOIN / 160].unwrap(),
        chao_to_hz(3.0, 100.0, 200.0),
        max_relative = 1e-4
    );
    let glide: Vec<f32> = (38..=42).map(|i| s.f0_truth[i].unwrap()).collect();
    assert!(glide.windows(2).all(|w| w[1] < w[0]), "{glide:?}");
    // A quarter of the way in (5 ms of 40), the cosine has moved (1 - cos(pi/4))/2 of the way.
    let quarter = 0.5 * (1.0 - std::f64::consts::FRAC_PI_4.cos()) as f32;
    let want = chao_to_hz(5.0 - 4.0 * quarter, 100.0, 200.0);
    assert_relative_eq!(s.f0_truth[39].unwrap(), want, max_relative = 1e-4);
}

#[test]
fn a_zero_glide_is_a_step() {
    let s = synth_fluent(&levels(0.0, 0.0));
    assert_relative_eq!(
        s.f0_truth[39].unwrap(),
        chao_to_hz(5.0, 100.0, 200.0),
        max_relative = 1e-5
    );
    assert_relative_eq!(
        s.f0_truth[40].unwrap(),
        chao_to_hz(1.0, 100.0, 200.0),
        max_relative = 1e-5
    );
}

#[test]
fn a_glide_never_takes_more_than_half_of_a_syllable() {
    // A 400 ms glide is cut to half of each 200 ms syllable: the middle syllable's centre is still
    // its own pitch only at its centre, and the outer syllables keep their first half.
    let s = synth_fluent(&levels(400.0, 0.0));
    assert_relative_eq!(
        s.f0_truth[25].unwrap(),
        chao_to_hz(5.0, 100.0, 200.0),
        max_relative = 1e-5
    );
    assert_relative_eq!(
        s.f0_truth[50].unwrap(),
        chao_to_hz(1.0, 100.0, 200.0),
        max_relative = 1e-4
    );
}

#[test]
fn the_dip_is_deepest_at_the_join_and_never_silent() {
    // One pitch throughout (200 Hz: each 10 ms window holds two whole periods), so only the dip
    // moves the level.
    let monotone = |dip_db| {
        spec(
            vec![syl(vec![5.0]), syl(vec![5.0]), syl(vec![5.0])],
            40.0,
            dip_db,
        )
    };
    for dip_db in [3.0, 6.0, 12.0] {
        let s = synth_fluent(&monotone(dip_db));
        let drop = level_db(&s.pcm, 4800) - level_db(&s.pcm, JOIN);
        // The 10 ms window averages the raised cosine a little shallower than its floor.
        assert!(
            (drop - f64::from(dip_db)).abs() < 0.2,
            "{dip_db} dB dip measured {drop:.2} dB"
        );
        // Outside the 80 ms dip the level is back to the syllable's.
        let outside = level_db(&s.pcm, 4800) - level_db(&s.pcm, JOIN + 50 * 16);
        assert!(outside.abs() < 0.05, "{outside:.2} dB");
    }
    let flat = synth_fluent(&monotone(0.0));
    let drop = level_db(&flat.pcm, 4800) - level_db(&flat.pcm, JOIN);
    assert!(drop.abs() < 0.05, "no dip measured {drop:.2} dB");
}

#[test]
fn a_fricative_onset_breaks_the_voicing_with_no_glide() {
    let mut onset = levels(40.0, 6.0);
    onset.syllables[1].unvoiced_onset_ms = 30.0;
    let s = synth_fluent(&onset);
    // Frames 40..43 are the onset: no pitch, but noise.
    assert!(s.f0_truth[40..43].iter().all(Option::is_none));
    assert!(rms(&s.pcm[JOIN..JOIN + 480]) > 0.01);
    // No glide on either side: the first syllable keeps Chao 5 to its end, the second starts at 1.
    assert_relative_eq!(
        s.f0_truth[39].unwrap(),
        chao_to_hz(5.0, 100.0, 200.0),
        max_relative = 1e-5
    );
    assert_relative_eq!(
        s.f0_truth[43].unwrap(),
        chao_to_hz(1.0, 100.0, 200.0),
        max_relative = 1e-5
    );
    // The other join is still voiced.
    assert!(s.f0_truth[43..80].iter().all(Option::is_some));
}

#[test]
fn snr_noise_depends_on_the_seed_and_leaves_the_truth_alone() {
    let mut noisy = levels(40.0, 3.0);
    noisy.snr_db = Some(25.0);
    let (a, b) = (synth_fluent(&noisy), synth_fluent(&noisy));
    assert_eq!(a, b);
    let mut other = noisy.clone();
    other.seed = 4;
    let c = synth_fluent(&other);
    assert_ne!(a.pcm, c.pcm);
    assert_eq!(a.f0_truth, c.f0_truth);
    assert_eq!(a.f0_truth, synth_fluent(&levels(40.0, 3.0)).f0_truth);
    // The lead is noise only.
    assert!(rms(&a.pcm[..3000]) > 0.0);
}

#[test]
fn speakers_have_their_documented_ranges_and_warm_registers() {
    let ranges: Vec<(&str, f32, f32)> = FLUENT_SPEAKERS
        .iter()
        .map(|s| (s.name, s.floor_hz, s.ceil_hz))
        .collect();
    assert_eq!(
        ranges,
        vec![
            ("male-low", 85.0, 160.0),
            ("octave-spanning", 100.0, 200.0),
            ("female", 180.0, 330.0),
            ("wide", 110.0, 260.0),
        ]
    );
    for s in FLUENT_SPEAKERS {
        assert_eq!(s.register(), register_for(s.floor_hz, s.ceil_hz));
    }
}
