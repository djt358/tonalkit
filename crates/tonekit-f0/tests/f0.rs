use tonekit_f0::*;
use tonekit_testkit::*;

/// One 400 ms syllable (no onset, gap or creak), Chao 1 = 100 Hz, Chao 5 = 200 Hz, 200 ms of
/// silence either side.
fn spec(chao: Vec<f32>, snr: Option<f32>) -> SynthSpec {
    SynthSpec {
        floor_hz: 100.0,
        ceil_hz: 200.0,
        lead_ms: 200.0,
        tail_ms: 200.0,
        syllables: vec![SynthSyllable {
            chao,
            dur_ms: 400.0,
            gap_after_ms: 0.0,
            unvoiced_onset_ms: 0.0,
            creak: None,
        }],
        snr_db: snr,
        seed: 1,
    }
}

fn voiced(hz: f32) -> tonekit_core::F0Frame {
    tonekit_core::F0Frame {
        hz: Some(hz),
        voiced_p: 0.9,
    }
}

fn unvoiced() -> tonekit_core::F0Frame {
    tonekit_core::F0Frame {
        hz: None,
        voiced_p: 0.0,
    }
}

fn track(frames: Vec<tonekit_core::F0Frame>) -> tonekit_core::F0Track {
    tonekit_core::F0Track {
        provider: "x".into(),
        frames,
    }
}

// --- Brief tests -------------------------------------------------------------------------------

#[test]
fn pyin_tracks_synthetic_f0_within_2pct() {
    let s = synth(&spec(vec![3.0, 5.0], None));
    let t = Pyin::default().track(&s.pcm);
    assert_eq!(t.frames.len(), s.f0_truth.len());
    let (a, b) = s.syllable_frames[0];
    let ok = (a + 3..b - 3)
        .filter(|&i| {
            let (tru, est) = (s.f0_truth[i as usize].unwrap(), t.frames[i as usize].hz);
            est.is_some_and(|e| (e - tru).abs() / tru < 0.02)
        })
        .count();
    assert!(ok as f32 / (b - a - 6) as f32 >= 0.95);
}

#[test]
fn silence_is_unvoiced() {
    let t = Pyin::default().track(&vec![0.0; 16_000]);
    assert!(t.frames.iter().all(|f| f.voiced_p < 0.5));
}

#[test]
fn energy_levels() {
    assert!(energy(&vec![0.0; 16_000]).db.iter().all(|&d| d <= -60.0));
    let sine: Vec<f32> = (0..16_000).map(|n| (n as f32 * 0.1).sin()).collect();
    approx::assert_abs_diff_eq!(energy(&sine).db[50], -3.0, epsilon = 0.5);
}

#[test]
fn octave_jump_repaired() {
    let mut t = tonekit_core::F0Track {
        provider: "x".into(),
        frames: (0..21)
            .map(|i| tonekit_core::F0Frame {
                hz: Some(if i == 10 { 300.0 } else { 150.0 }),
                voiced_p: 0.9,
            })
            .collect(),
    };
    repair_octaves(&mut t);
    approx::assert_relative_eq!(t.frames[10].hz.unwrap(), 150.0, max_relative = 0.01);
}

#[test]
fn clipping_and_snr() {
    let mut x = vec![0.1f32; 1000];
    for v in x.iter_mut().take(20) {
        *v = 1.0;
    }
    approx::assert_abs_diff_eq!(clipping_ratio(&x), 0.02, epsilon = 1e-6);
    let noisy = synth(&spec(vec![5.0, 5.0], Some(5.0)));
    assert!(snr_db(&energy(&noisy.pcm)) < snr_db(&energy(&synth(&spec(vec![5.0, 5.0], None)).pcm)));
}

// --- Provider ----------------------------------------------------------------------------------

#[test]
fn pyin_default_range_and_name() {
    let p = Pyin::default();
    assert_eq!((p.fmin, p.fmax), (50.0, 600.0));
    assert_eq!(p.name(), "pyin");
    assert_eq!(p.track(&[0.0; 320]).provider, "pyin");
}

#[test]
fn pyin_frame_count_holds_for_any_length() {
    let p = Pyin::default();
    for n in [0usize, 1, 159, 160, 161, 1000, 1023, 1024, 1025, 1600] {
        let pcm: Vec<f32> = (0..n).map(|i| 0.3 * (i as f32 * 0.05).sin()).collect();
        let t = p.track(&pcm);
        assert_eq!(t.frames.len(), n / 160 + 1, "length {n}");
        assert!(
            t.frames.iter().all(|f| f.voiced_p.is_finite()),
            "length {n}"
        );
    }
}

#[test]
fn pyin_survives_noise_and_non_finite_samples() {
    let p = Pyin::default();
    // A deterministic pseudo-noise burst (no rand dependency).
    let mut state = 0x2545_f491_4f6c_dd1du64;
    let noise: Vec<f32> = (0..3200)
        .map(|_| {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            (state >> 40) as f32 / (1u64 << 24) as f32 - 0.5
        })
        .collect();
    assert_eq!(p.track(&noise).frames.len(), 3200 / 160 + 1);

    let mut bad = noise.clone();
    bad[100] = f32::NAN;
    bad[1000] = f32::INFINITY;
    bad[2500] = f32::NEG_INFINITY;
    let t = p.track(&bad);
    assert_eq!(t.frames.len(), 3200 / 160 + 1);
    assert!(t.frames.iter().all(|f| f.voiced_p.is_finite()));
    assert!(t.frames.iter().all(|f| f.hz.is_none_or(f32::is_finite)));
}

#[test]
fn pyin_hz_is_none_or_inside_the_search_range() {
    let s = synth(&spec(vec![1.0, 5.0], None));
    let t = Pyin::default().track(&s.pcm);
    for f in &t.frames {
        if let Some(hz) = f.hz {
            assert!((49.0..=601.0).contains(&hz), "hz {hz} outside 50..600");
        }
    }
}

#[test]
fn pyin_range_support_boundaries() {
    let ok = |fmin: f32, fmax: f32| Pyin { fmin, fmax }.range_supported();
    assert!(Pyin::default().range_supported());
    assert!(ok(80.0, 400.0));
    assert!(ok(50.0, 63.5)); // just wide enough for the transition kernel (>1.26 : 1)
    assert!(ok(31.4, 600.0)); // longest lag 510 samples, inside the 511-sample limit
    assert!(ok(32.0, 8000.0)); // Nyquist is allowed
    assert!(!ok(50.0, 63.1)); // too narrow
    assert!(!ok(599.0, 600.0));
    assert!(!ok(31.3, 600.0)); // longest lag 512 samples: fmin would be silently raised
    assert!(!ok(10.0, 15.0));
    assert!(!ok(0.0, 600.0));
    assert!(!ok(-50.0, 600.0));
    assert!(!ok(600.0, 50.0));
    assert!(!ok(300.0, 300.0));
    assert!(!ok(50.0, 8000.5)); // above Nyquist
    assert!(!ok(f32::NAN, 600.0));
    assert!(!ok(50.0, f32::NAN));
    assert!(!ok(50.0, f32::INFINITY));
    assert!(!ok(f32::INFINITY, f32::INFINITY));
}

#[test]
fn pyin_unsupported_range_gives_an_unvoiced_track_not_a_panic() {
    let pcm: Vec<f32> = (0..1600).map(|i| 0.3 * (i as f32 * 0.05).sin()).collect();
    for (fmin, fmax) in [
        (0.0, 600.0),
        (600.0, 50.0),
        (599.0, 600.0),
        (f32::NAN, 600.0),
    ] {
        let t = Pyin { fmin, fmax }.track(&pcm);
        assert_eq!(t.provider, "pyin");
        assert_eq!(t.frames.len(), 1600 / 160 + 1);
        assert!(t.frames.iter().all(|f| *f == unvoiced()), "{fmin}..{fmax}");
    }
}

#[test]
fn pyin_runs_on_supported_ranges_at_the_edges() {
    let pcm: Vec<f32> = (0..1600).map(|i| 0.3 * (i as f32 * 0.05).sin()).collect();
    for (fmin, fmax) in [(50.0, 63.5), (31.4, 600.0), (80.0, 400.0)] {
        let p = Pyin { fmin, fmax };
        assert!(p.range_supported());
        let t = p.track(&pcm);
        assert_eq!(t.frames.len(), 1600 / 160 + 1, "{fmin}..{fmax}");
        for hz in t.frames.iter().filter_map(|f| f.hz) {
            assert!(
                (fmin * 0.99..=fmax * 1.01).contains(&hz),
                "{hz} outside {fmin}..{fmax}"
            );
        }
    }
}

// --- fit_length --------------------------------------------------------------------------------

#[test]
fn fit_length_truncates_pads_and_keeps_provider() {
    let t = track(vec![voiced(100.0), voiced(110.0), voiced(120.0)]);

    let shorter = fit_length(t.clone(), 2);
    assert_eq!(shorter.frames, vec![voiced(100.0), voiced(110.0)]);
    assert_eq!(shorter.provider, "x");

    let same = fit_length(t.clone(), 3);
    assert_eq!(same, t);

    let longer = fit_length(t.clone(), 5);
    assert_eq!(longer.frames.len(), 5);
    assert_eq!(&longer.frames[..3], &t.frames[..]);
    assert_eq!(&longer.frames[3..], &[unvoiced(), unvoiced()]);
    assert_eq!(longer.provider, "x");

    assert!(fit_length(t, 0).frames.is_empty());
}

// --- Energy ------------------------------------------------------------------------------------

#[test]
fn energy_has_one_frame_per_hop_plus_one() {
    for (n, frames) in [
        (0usize, 1usize),
        (159, 1),
        (160, 2),
        (480, 4),
        (16_000, 101),
    ] {
        assert_eq!(energy(&vec![0.0; n]).db.len(), frames, "length {n}");
    }
}

#[test]
fn energy_floor_is_minus_100_db() {
    assert!(energy(&vec![0.0; 1600]).db.iter().all(|&d| d == -100.0));
    // Far below the floor still reads -100.
    let tiny = vec![1e-9f32; 1600];
    assert!(energy(&tiny).db.iter().all(|&d| d == -100.0));
}

#[test]
fn energy_windows_are_centred_and_zero_padded() {
    // A constant signal fills the window everywhere except the edges: frame 0 is centred on
    // sample 0, so half of its window is zero padding and it reads about 3 dB below the middle
    // (Hann² is symmetric, so half the weight is missing).
    let dc = vec![1.0f32; 3200];
    let e = energy(&dc);
    approx::assert_abs_diff_eq!(e.db[10], 0.0, epsilon = 1e-3);
    approx::assert_abs_diff_eq!(e.db[0], -3.0, epsilon = 0.1);
    let last = e.db.len() - 1;
    approx::assert_abs_diff_eq!(e.db[last], -3.0, epsilon = 0.1);
}

#[test]
fn energy_follows_a_click_at_its_own_frame() {
    // A single impulse at sample 800 (frame 5's centre) is at the window peak for frame 5 and
    // falls off symmetrically either side.
    let mut x = vec![0.0f32; 1600];
    x[800] = 1.0;
    let e = energy(&x);
    let peak = (0..e.db.len())
        .max_by(|&a, &b| e.db[a].total_cmp(&e.db[b]))
        .unwrap();
    assert_eq!(peak, 5);
    approx::assert_abs_diff_eq!(e.db[4], e.db[6], epsilon = 1e-4);
    assert!(e.db[5] > e.db[4]);
}

#[test]
fn energy_treats_non_finite_samples_as_silence() {
    let mut x = vec![0.5f32; 1600];
    let clean = energy(&x);
    x[700] = f32::NAN;
    x[900] = f32::INFINITY;
    x[901] = f32::NEG_INFINITY;
    let dirty = energy(&x);
    assert!(dirty.db.iter().all(|d| d.is_finite()));
    // Frames far from the bad samples are untouched; a frame whose window holds them dips.
    approx::assert_abs_diff_eq!(dirty.db[2], clean.db[2], epsilon = 1e-6);
    assert!(dirty.db[5] < clean.db[5]);
}

// --- Octave repair -----------------------------------------------------------------------------

#[test]
fn octave_jump_down_is_repaired_too() {
    let mut t = track(
        (0..21)
            .map(|i| voiced(if i == 10 { 75.0 } else { 150.0 }))
            .collect(),
    );
    repair_octaves(&mut t);
    approx::assert_relative_eq!(t.frames[10].hz.unwrap(), 150.0, max_relative = 0.01);
}

#[test]
fn smooth_and_moderate_tracks_are_left_alone() {
    // A rising glide of 8 st over the track, and a jump of 7 st: neither exceeds 9 st.
    let glide: Vec<_> = (0..40)
        .map(|i| voiced(100.0 * (8.0 * i as f32 / 39.0 / 12.0).exp2()))
        .collect();
    let mut t = track(glide);
    let before = t.clone();
    repair_octaves(&mut t);
    assert_eq!(t, before);

    let jump7 = 150.0 * (7.0f32 / 12.0).exp2();
    let mut t = track(
        (0..21)
            .map(|i| voiced(if i == 10 { jump7 } else { 150.0 }))
            .collect(),
    );
    let before = t.clone();
    repair_octaves(&mut t);
    assert_eq!(t, before);
}

#[test]
fn repair_only_touches_voiced_frames() {
    let mut frames: Vec<_> = (0..21).map(|_| voiced(150.0)).collect();
    frames[10] = unvoiced();
    // Hz set but not voiced enough: not a voiced frame, so neither repaired nor used as a neighbour.
    frames[4] = tonekit_core::F0Frame {
        hz: Some(300.0),
        voiced_p: 0.2,
    };
    let mut t = track(frames);
    let before = t.clone();
    repair_octaves(&mut t);
    assert_eq!(t, before);
}

#[test]
fn repair_neighbours_skip_unvoiced_frames_and_use_original_values() {
    // Six voiced frames, an unvoiced gap, then a lone octave-high frame, another gap and six more
    // voiced frames: the lone frame's neighbours are the nearest voiced ones on each side.
    let mut frames = vec![voiced(150.0); 6];
    frames.extend(vec![unvoiced(); 8]);
    frames.push(voiced(310.0));
    frames.extend(vec![unvoiced(); 8]);
    frames.extend(vec![voiced(150.0); 6]);
    let mut t = track(frames);
    repair_octaves(&mut t);
    approx::assert_relative_eq!(t.frames[14].hz.unwrap(), 155.0, max_relative = 1e-5);
    // The neighbours themselves are unchanged even though one of their neighbours was wrong.
    assert!(t.frames[..6].iter().all(|f| f.hz == Some(150.0)));
    assert!(t.frames[23..].iter().all(|f| f.hz == Some(150.0)));
}

#[test]
fn isolated_voiced_frame_has_no_neighbours_and_is_kept() {
    let mut frames = vec![unvoiced(); 11];
    frames[5] = voiced(400.0);
    let mut t = track(frames);
    let before = t.clone();
    repair_octaves(&mut t);
    assert_eq!(t, before);
}

#[test]
fn repair_handles_empty_and_short_tracks() {
    let mut t = track(vec![]);
    repair_octaves(&mut t);
    assert!(t.frames.is_empty());
    let mut t = track(vec![voiced(150.0), voiced(300.0)]);
    repair_octaves(&mut t);
    // Two frames disagree by 12 st, each one's only neighbour is the other: both shift toward the
    // other from the original values, so they swap sides rather than converge. Single pass by rule.
    assert_eq!(t.frames.len(), 2);
}

#[test]
fn repair_leaves_a_two_octave_error_half_fixed() {
    // A single ±12 st shift per frame, not repeated: 600 Hz vs 150 Hz (24 st) ends at 300 Hz.
    let mut t = track(
        (0..21)
            .map(|i| voiced(if i == 10 { 600.0 } else { 150.0 }))
            .collect(),
    );
    repair_octaves(&mut t);
    approx::assert_relative_eq!(t.frames[10].hz.unwrap(), 300.0, max_relative = 1e-5);
}

#[test]
fn repair_fixes_a_pyin_style_synthetic_octave_error() {
    // End to end on the synthetic voice: inject an octave-doubling error and repair it.
    let s = synth(&spec(vec![3.0, 4.0], None));
    let mut t = Pyin::default().track(&s.pcm);
    let (a, b) = s.syllable_frames[0];
    let mid = ((a + b) / 2) as usize;
    let good = t.frames[mid].hz.expect("mid-syllable frame is voiced");
    t.frames[mid].hz = Some(good * 2.0);
    repair_octaves(&mut t);
    approx::assert_relative_eq!(t.frames[mid].hz.unwrap(), good, max_relative = 0.05);
}

#[test]
fn octave_error_at_the_edge_of_a_track_is_repaired() {
    // The first frame has only right-hand neighbours; the last only left-hand ones.
    let mut frames: Vec<_> = (0..12).map(|_| voiced(150.0)).collect();
    frames[0] = voiced(300.0);
    frames[11] = voiced(75.0);
    let mut t = track(frames);
    repair_octaves(&mut t);
    approx::assert_relative_eq!(t.frames[0].hz.unwrap(), 150.0, max_relative = 1e-5);
    approx::assert_relative_eq!(t.frames[11].hz.unwrap(), 150.0, max_relative = 1e-5);
    assert!(t.frames[1..11].iter().all(|f| f.hz == Some(150.0)));
}

#[test]
fn repair_keeps_voiced_p_and_shifts_by_exactly_an_octave() {
    let mut frames: Vec<_> = (0..21).map(|_| voiced(150.0)).collect();
    frames[10] = tonekit_core::F0Frame {
        hz: Some(301.0),
        voiced_p: 0.77,
    };
    let mut t = track(frames);
    repair_octaves(&mut t);
    assert_eq!(t.frames[10].hz, Some(150.5));
    assert_eq!(t.frames[10].voiced_p, 0.77);
    assert_eq!(t.provider, "x");
}

#[test]
fn repair_consults_exactly_five_neighbours_each_side() {
    // Frame 0 is 300 Hz (29.4 st) with only right-hand neighbours: 150 Hz is 17.4 st and 600 Hz
    // is 41.4 st. Only the first five voiced frames after it may vote.
    let first_frame_after = |right: &[f32]| {
        let mut frames = vec![voiced(300.0)];
        frames.extend(right.iter().map(|&hz| voiced(hz)));
        let mut t = track(frames);
        repair_octaves(&mut t);
        t.frames[0].hz.unwrap()
    };
    // A: three low, then high. Five voters [L L L H H] have median 150, so 300 drops to 150.
    // A sixth voter would make it 3:3, whose median is halfway (29.4 st): no repair.
    let a = first_frame_after(&[
        150.0, 150.0, 150.0, 600.0, 600.0, 600.0, 600.0, 600.0, 600.0,
    ]);
    approx::assert_relative_eq!(a, 150.0, max_relative = 1e-5);
    // B: two low, then high. Five voters [L L H H H] have median 600, so 300 rises to 600.
    // Only four voters would make it 2:2 (median halfway): no repair.
    let b = first_frame_after(&[
        150.0, 150.0, 600.0, 600.0, 600.0, 600.0, 600.0, 600.0, 600.0,
    ]);
    approx::assert_relative_eq!(b, 600.0, max_relative = 1e-5);
}

// --- Clipping and SNR --------------------------------------------------------------------------

#[test]
fn clipping_ratio_edges() {
    assert_eq!(clipping_ratio(&[]), 0.0);
    assert_eq!(clipping_ratio(&[0.0; 100]), 0.0);
    // |x| >= 0.99 counts, in either sign; 0.98 does not.
    let x = [0.99f32, -0.99, 1.0, -1.0, 0.98, -0.98, 0.5, 0.0];
    approx::assert_abs_diff_eq!(clipping_ratio(&x), 0.5, epsilon = 1e-6);
}

#[test]
fn snr_db_is_p95_minus_p10_with_linear_interpolation() {
    let ramp = tonekit_core::EnergyTrack {
        db: (0..=100).map(|i| i as f32).collect(),
    };
    approx::assert_abs_diff_eq!(snr_db(&ramp), 85.0, epsilon = 1e-4);
    // Order does not matter.
    let shuffled = tonekit_core::EnergyTrack {
        db: (0..=100).rev().map(|i| i as f32).collect(),
    };
    approx::assert_abs_diff_eq!(snr_db(&shuffled), 85.0, epsilon = 1e-4);
    // 11 values 0..10: p95 sits at index 9.5, p10 at index 1.0.
    let eleven = tonekit_core::EnergyTrack {
        db: (0..=10).map(|i| i as f32).collect(),
    };
    approx::assert_abs_diff_eq!(snr_db(&eleven), 9.5 - 1.0, epsilon = 1e-4);
    let flat = tonekit_core::EnergyTrack {
        db: vec![-30.0; 50],
    };
    assert_eq!(snr_db(&flat), 0.0);
    let one = tonekit_core::EnergyTrack { db: vec![-30.0] };
    assert_eq!(snr_db(&one), 0.0);
    let none = tonekit_core::EnergyTrack { db: vec![] };
    assert_eq!(snr_db(&none), 0.0);
}

#[test]
fn clean_synthetic_speech_has_a_wide_dynamic_range_and_noisy_a_narrow_one() {
    let clean = snr_db(&energy(&synth(&spec(vec![5.0, 5.0], None)).pcm));
    let noisy = snr_db(&energy(&synth(&spec(vec![5.0, 5.0], Some(5.0))).pcm));
    assert!(clean > 40.0, "clean {clean}");
    assert!(noisy < 10.0, "noisy {noisy}");
}

#[test]
fn snr_db_ignores_non_finite_frames() {
    let e = tonekit_core::EnergyTrack {
        db: vec![f32::NAN, 0.0, 50.0, f32::INFINITY, 100.0, f32::NEG_INFINITY],
    };
    // Finite frames 0, 50, 100: p95 = 95, p10 = 10.
    approx::assert_abs_diff_eq!(snr_db(&e), 85.0, epsilon = 1e-4);
}
