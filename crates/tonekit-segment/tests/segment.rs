use approx::assert_abs_diff_eq;
use proptest::prelude::*;
use tonekit_core::{EnergyTrack, F0Frame, F0Track, FrameRange, Nucleus};
use tonekit_f0::{energy, F0Provider, Pyin};
use tonekit_segment::{
    boundaries, boundaries_with, nuclei, speech_region, speech_threshold, SegmentParams,
};
use tonekit_testkit::{synth, Synth, SynthSpec, SynthSyllable};

// --- Synthetic-speech helpers ------------------------------------------------------------------

/// `n` syllables of 250 ms (Chao [3, 4], gentle), `gap_ms` of silence after each, floor 100 Hz /
/// ceil 200 Hz, 200 ms of lead and tail, seed 1.
fn n_syllables(n: usize, gap_ms: f32) -> SynthSpec {
    with_chao(vec![vec![3.0, 4.0]; n], gap_ms, 0.0)
}

fn with_chao(chao: Vec<Vec<f32>>, gap_ms: f32, unvoiced_onset_ms: f32) -> SynthSpec {
    SynthSpec {
        floor_hz: 100.0,
        ceil_hz: 200.0,
        lead_ms: 200.0,
        tail_ms: 200.0,
        syllables: chao
            .into_iter()
            .map(|chao| SynthSyllable {
                chao,
                dur_ms: 250.0,
                gap_after_ms: gap_ms,
                unvoiced_onset_ms,
                creak: None,
            })
            .collect(),
        snr_db: None,
        seed: 1,
    }
}

/// Everything the segmenter produces for one synthetic utterance, with a real pYIN f0 track (what
/// production feeds this crate).
struct Run {
    synth: Synth,
    region: FrameRange,
    nuclei: Vec<Nucleus>,
    boundaries: Vec<u32>,
}

fn run(spec: &SynthSpec) -> Run {
    let s = synth(spec);
    let f0 = Pyin::default().track(&s.pcm);
    run_with(s, f0)
}

fn run_with(s: Synth, f0: F0Track) -> Run {
    let p = SegmentParams::default();
    let e = energy(&s.pcm);
    let region = speech_region(&e, &p).expect("speech present");
    let nuclei = nuclei(&e, &f0, &region, &p);
    let boundaries = boundaries(&e, &f0, &region, &nuclei);
    Run {
        synth: s,
        region,
        nuclei,
        boundaries,
    }
}

/// A track built from the synthesiser's ground truth: voiced (`voiced_p` 1) exactly where the
/// signal is harmonic. Used where a test needs exact voicing edges.
fn truth_track(s: &Synth) -> F0Track {
    F0Track {
        provider: "truth".into(),
        frames: s
            .f0_truth
            .iter()
            .map(|&hz| F0Frame {
                hz,
                voiced_p: if hz.is_some() { 1.0 } else { 0.0 },
            })
            .collect(),
    }
}

// --- Hand-built track helpers ------------------------------------------------------------------

/// Piecewise-linear dB curve through `(frame, db)` knots, `len` frames long (flat past the ends).
fn curve(len: usize, knots: &[(usize, f32)]) -> EnergyTrack {
    let db = (0..len)
        .map(|i| {
            let k = knots.iter().position(|&(f, _)| f >= i);
            match k {
                None => knots.last().unwrap().1,
                Some(0) => knots[0].1,
                Some(k) => {
                    let ((f0, d0), (f1, d1)) = (knots[k - 1], knots[k]);
                    d0 + (d1 - d0) * (i - f0) as f32 / (f1 - f0) as f32
                }
            }
        })
        .collect();
    EnergyTrack { db }
}

/// An f0 track voiced (`voiced_p` given per frame, hz 150 when >= 0.5).
fn voicing(voiced_p: &[f32]) -> F0Track {
    F0Track {
        provider: "hand".into(),
        frames: voiced_p
            .iter()
            .map(|&p| F0Frame {
                hz: (p >= 0.5).then_some(150.0),
                voiced_p: p,
            })
            .collect(),
    }
}

fn all_voiced(len: usize) -> F0Track {
    voicing(&vec![1.0; len])
}

fn nuc(frame: u32) -> Nucleus {
    Nucleus {
        frame,
        strength_db: 30.0,
    }
}

fn range(start: u32, end: u32) -> FrameRange {
    FrameRange { start, end }
}

/// Two loud peaks on a -60 dB floor: 20 and 40 with a valley `valley` dB at frame 30.
fn two_peaks(peak_a: f32, peak_b: f32, valley: f32) -> EnergyTrack {
    curve(
        100,
        &[
            (0, -60.0),
            (10, -60.0),
            (20, peak_a),
            (30, valley),
            (40, peak_b),
            (50, -60.0),
            (99, -60.0),
        ],
    )
}

// --- Brief tests -------------------------------------------------------------------------------

#[test]
fn three_separated_syllables_three_nuclei() {
    // gap 120 ms: nuclei.len() == 3, and a boundary strictly inside each gap.
    let r = run(&n_syllables(3, 120.0));
    assert_eq!(r.nuclei.len(), 3, "nuclei {:?}", r.nuclei);
    let frames = &r.synth.syllable_frames;
    for (k, n) in r.nuclei.iter().enumerate() {
        let (a, b) = frames[k];
        assert!((a..b).contains(&n.frame), "nucleus {k} at {}", n.frame);
    }
    for k in 0..2 {
        let (gap_start, gap_end) = (frames[k].1, frames[k + 1].0);
        assert!(
            r.boundaries.iter().any(|&b| b > gap_start && b < gap_end),
            "no boundary inside gap {k} {gap_start}..{gap_end}: {:?}",
            r.boundaries
        );
    }
}

#[test]
fn three_contiguous_syllables_still_three_nuclei() {
    // gap 0 ms: only the per-syllable amplitude ramps make dips, and that is enough.
    let r = run(&n_syllables(3, 0.0));
    assert_eq!(r.nuclei.len(), 3, "nuclei {:?}", r.nuclei);
    let frames = &r.synth.syllable_frames;
    for (k, n) in r.nuclei.iter().enumerate() {
        let (a, b) = frames[k];
        assert!((a..b).contains(&n.frame), "nucleus {k} at {}", n.frame);
    }
    // ... and each junction is a boundary candidate (+-2 frames).
    for junction in frames.windows(2).map(|w| w[0].1) {
        assert!(
            r.boundaries.iter().any(|&b| b.abs_diff(junction) <= 2),
            "no boundary near junction {junction}: {:?}",
            r.boundaries
        );
    }
}

#[test]
fn silence_has_no_region() {
    assert!(speech_region(&energy(&vec![0.0; 16000]), &Default::default()).is_none());
}

#[test]
fn unvoiced_onset_yields_voicing_boundary() {
    // 60 ms of noise before the voiced part of a single syllable; the voicing onset is the first
    // frame whose signal is harmonic. With an exact (truth-built) f0 track ...
    let spec = with_chao(vec![vec![3.0, 4.0]], 0.0, 60.0);
    let s = synth(&spec);
    let onset = s.f0_truth.iter().position(Option::is_some).unwrap() as u32;
    let r = run_with(s.clone(), truth_track(&s));
    assert!(
        onset > r.region.start + 2,
        "the noise onset must be part of the region, else this test proves nothing"
    );
    assert!(
        r.boundaries.iter().any(|&b| b.abs_diff(onset) <= 2),
        "no boundary within 2 frames of voicing onset {onset}: {:?}",
        r.boundaries
    );

    // ... and with real pYIN, whose voicing edge may sit a frame or two later.
    let r = run_with(s.clone(), Pyin::default().track(&s.pcm));
    assert!(
        r.boundaries.iter().any(|&b| b.abs_diff(onset) <= 2),
        "pYIN: no boundary within 2 frames of voicing onset {onset}: {:?}",
        r.boundaries
    );
}

#[test]
fn boundary_count_is_capped() {
    // Real audio: whatever the utterance, boundaries.len() <= 4 * nuclei.len() + 2.
    for spec in [
        n_syllables(1, 0.0),
        n_syllables(3, 120.0),
        n_syllables(3, 0.0),
        n_syllables(4, 40.0),
        with_chao(
            vec![vec![2.0, 1.0, 4.0], vec![5.0, 5.0], vec![5.0, 1.0]],
            60.0,
            40.0,
        ),
    ] {
        let r = run(&spec);
        assert!(
            r.boundaries.len() <= 4 * r.nuclei.len() + 2,
            "{} boundaries for {} nuclei",
            r.boundaries.len(),
            r.nuclei.len()
        );
    }
}

// --- Speech region and threshold ---------------------------------------------------------------

#[test]
fn defaults_are_the_segmentation_seeds() {
    let p = SegmentParams::default();
    assert_eq!(p.speech_margin_db, 10.0);
    assert_eq!(p.dip_db, 2.0);
    assert_eq!(p.min_nucleus_gap, 6);
}

#[test]
fn threshold_is_p10_plus_margin() {
    // 20 quiet frames and 80 loud ones: the 10th percentile is the quiet level.
    let mut db = vec![-60.0; 20];
    db.extend(vec![-20.0; 80]);
    let e = EnergyTrack { db };
    assert_abs_diff_eq!(
        speech_threshold(&e, &Default::default()),
        -50.0,
        epsilon = 1e-4
    );
    let p = SegmentParams {
        speech_margin_db: 3.0,
        ..Default::default()
    };
    assert_abs_diff_eq!(speech_threshold(&e, &p), -57.0, epsilon = 1e-4);
}

#[test]
fn threshold_interpolates_percentile_and_ignores_non_finite() {
    // Sorted: rank 0.1 * 10 = 1.0 exactly -> the second-lowest finite value.
    let mut db: Vec<f32> = (0..11).map(|i| -50.0 + i as f32).collect();
    db.push(f32::NAN);
    db.push(f32::NEG_INFINITY);
    let e = EnergyTrack { db };
    assert_abs_diff_eq!(
        speech_threshold(&e, &Default::default()),
        -49.0 + 10.0,
        epsilon = 1e-4
    );
}

#[test]
fn empty_track_has_no_speech() {
    let e = EnergyTrack { db: vec![] };
    assert!(speech_threshold(&e, &Default::default()).is_infinite());
    assert!(speech_region(&e, &Default::default()).is_none());
}

#[test]
fn region_needs_five_frames_above_threshold() {
    let mut db = vec![-60.0; 100];
    for f in db.iter_mut().skip(40).take(4) {
        *f = -20.0;
    }
    assert!(speech_region(&EnergyTrack { db: db.clone() }, &Default::default()).is_none());
    db[44] = -20.0;
    assert_eq!(
        speech_region(&EnergyTrack { db }, &Default::default()),
        Some(range(40, 45))
    );
}

#[test]
fn region_spans_first_to_last_loud_frame_half_open() {
    // Two loud bursts with a quiet gap between them: one region, gap included, `end` exclusive.
    let mut db = vec![-60.0; 100];
    for f in db.iter_mut().take(26).skip(20) {
        *f = -20.0;
    }
    for f in db.iter_mut().take(67).skip(60) {
        *f = -20.0;
    }
    assert_eq!(
        speech_region(&EnergyTrack { db }, &Default::default()),
        Some(range(20, 67))
    );
}

#[test]
fn constant_energy_is_not_speech() {
    // Nothing is 10 dB above its own floor.
    let e = EnergyTrack {
        db: vec![-30.0; 200],
    };
    assert!(speech_region(&e, &Default::default()).is_none());
}

// --- Nuclei ------------------------------------------------------------------------------------

/// The 5-frame moving average at `i`, computed independently of the crate.
fn smoothed_at(e: &EnergyTrack, i: usize) -> f32 {
    e.db[i - 2..=i + 2].iter().sum::<f32>() / 5.0
}

#[test]
fn nuclei_of_two_separated_peaks() {
    let e = two_peaks(-20.0, -22.0, -50.0);
    let p = SegmentParams::default();
    let region = speech_region(&e, &p).unwrap();
    let ns = nuclei(&e, &all_voiced(100), &region, &p);
    assert_eq!(ns.len(), 2, "{ns:?}");
    assert_eq!(ns[0].frame, 20);
    assert_eq!(ns[1].frame, 40);
    // strength_db = smoothed peak - p10 (the floor, -60 dB).
    assert_abs_diff_eq!(
        ns[0].strength_db,
        smoothed_at(&e, 20) + 60.0,
        epsilon = 1e-3
    );
    assert_abs_diff_eq!(
        ns[1].strength_db,
        smoothed_at(&e, 40) + 60.0,
        epsilon = 1e-3
    );
}

#[test]
fn shallow_dip_merges_and_keeps_the_higher_peak() {
    // Valley only ~1 dB under the lower peak (< dip_db = 2): one nucleus, at the higher peak.
    let p = SegmentParams::default();
    let e = two_peaks(-20.0, -20.5, -21.5);
    let region = speech_region(&e, &p).unwrap();
    let ns = nuclei(&e, &all_voiced(100), &region, &p);
    assert_eq!(ns.len(), 1, "{ns:?}");
    // (The smoothed maximum sits a frame or two off the corner of the piecewise-linear curve.)
    assert!(ns[0].frame.abs_diff(20) <= 3, "{ns:?}");

    let e = two_peaks(-20.5, -20.0, -21.5);
    let region = speech_region(&e, &p).unwrap();
    let ns = nuclei(&e, &all_voiced(100), &region, &p);
    assert_eq!(ns.len(), 1, "{ns:?}");
    assert!(ns[0].frame.abs_diff(40) <= 3, "{ns:?}");
}

#[test]
fn dip_deeper_than_dip_db_keeps_both() {
    let p = SegmentParams::default();
    let e = two_peaks(-20.0, -20.5, -25.0);
    let region = speech_region(&e, &p).unwrap();
    assert_eq!(nuclei(&e, &all_voiced(100), &region, &p).len(), 2);
    // The dip threshold is a parameter.
    let wide = SegmentParams { dip_db: 8.0, ..p };
    assert_eq!(nuclei(&e, &all_voiced(100), &region, &wide).len(), 1);
}

#[test]
fn close_peaks_merge_even_across_a_deep_dip() {
    // Peaks 20 frames apart with a deep valley: distinct under the default spacing (6 frames),
    // one nucleus once the minimum spacing exceeds their distance.
    let p = SegmentParams::default();
    let e = two_peaks(-20.0, -22.0, -50.0);
    let region = speech_region(&e, &p).unwrap();
    assert_eq!(nuclei(&e, &all_voiced(100), &region, &p).len(), 2);
    let far = SegmentParams {
        min_nucleus_gap: 30,
        ..p
    };
    let ns = nuclei(&e, &all_voiced(100), &region, &far);
    assert_eq!(ns.len(), 1);
    assert_eq!(ns[0].frame, 20, "keeps the higher peak");
}

/// An f0 track with a pitch (`hz` Some) on exactly the frames where `pitched` is true, and
/// `voiced_p` the same everywhere.
fn pitch_where(len: usize, pitched: impl Fn(usize) -> bool, voiced_p: f32) -> F0Track {
    F0Track {
        provider: "hand".into(),
        frames: (0..len)
            .map(|i| F0Frame {
                hz: pitched(i).then_some(150.0),
                voiced_p,
            })
            .collect(),
    }
}

#[test]
fn nucleus_needs_a_pitch_within_two_frames_of_the_peak() {
    // R27: periodicity is `hz.is_some()` on any frame within +-2 of the peak, whatever `voiced_p`
    // says. The peaks are at 20 and 40.
    let p = SegmentParams::default();
    let e = two_peaks(-20.0, -22.0, -50.0);
    let region = speech_region(&e, &p).unwrap();
    let frames = |f0: &F0Track| -> Vec<u32> {
        nuclei(&e, f0, &region, &p)
            .iter()
            .map(|n| n.frame)
            .collect()
    };

    // A pitch at 42 (two frames past the second peak) and around the first: both count, even
    // though voiced_p is 0 everywhere.
    let f0 = pitch_where(100, |i| (15..=22).contains(&i) || i == 42, 0.0);
    assert_eq!(frames(&f0), vec![20, 40]);
    // A pitch at 43 (three frames away) does not.
    let f0 = pitch_where(100, |i| (15..=22).contains(&i) || i == 43, 0.0);
    assert_eq!(frames(&f0), vec![20]);
    // Pitch on the low side only (frame 38) counts the same way.
    let f0 = pitch_where(100, |i| (15..=22).contains(&i) || i == 38, 0.0);
    assert_eq!(frames(&f0), vec![20, 40]);
    // voiced_p = 1 with no pitch anywhere is not periodicity.
    assert!(frames(&pitch_where(100, |_| false, 1.0)).is_empty());
    // A pitch elsewhere in the syllable, far from the peak, does not matter.
    let f0 = pitch_where(
        100,
        |i| (15..=22).contains(&i) || (30..=36).contains(&i),
        1.0,
    );
    assert_eq!(frames(&f0), vec![20]);
}

#[test]
fn peak_below_the_speech_threshold_is_not_a_nucleus() {
    // Loud, a dip under the threshold, a bump that stays under it (inside the region), loud again.
    let p = SegmentParams::default();
    let e = curve(
        120,
        &[
            (0, -60.0),
            (10, -60.0),
            (20, -20.0),
            (30, -60.0),
            (45, -54.0),
            (60, -60.0),
            (70, -20.0),
            (80, -60.0),
            (119, -60.0),
        ],
    );
    let region = speech_region(&e, &p).unwrap();
    assert!(region.start < 45 && 45 < region.end);
    let ns = nuclei(&e, &all_voiced(120), &region, &p);
    assert_eq!(ns.iter().map(|n| n.frame).collect::<Vec<_>>(), vec![20, 70]);
}

#[test]
fn nuclei_stay_inside_the_region() {
    let p = SegmentParams::default();
    let e = two_peaks(-20.0, -22.0, -50.0);
    let ns = nuclei(&e, &all_voiced(100), &range(0, 35), &p);
    assert_eq!(ns.iter().map(|n| n.frame).collect::<Vec<_>>(), vec![20]);
    assert!(nuclei(&e, &all_voiced(100), &range(50, 100), &p).is_empty());
}

#[test]
fn flat_topped_peak_is_one_nucleus_at_its_middle() {
    let p = SegmentParams::default();
    let e = curve(
        100,
        &[
            (0, -60.0),
            (10, -60.0),
            (20, -20.0),
            (30, -20.0),
            (40, -60.0),
            (99, -60.0),
        ],
    );
    let region = speech_region(&e, &p).unwrap();
    let ns = nuclei(&e, &all_voiced(100), &region, &p);
    assert_eq!(ns.len(), 1, "{ns:?}");
    assert!((24..=26).contains(&ns[0].frame), "{ns:?}");
}

#[test]
fn whispered_speech_has_a_region_but_no_nuclei() {
    // Fully unvoiced syllables: energy is there, voicing is not.
    let spec = with_chao(vec![vec![]; 2], 60.0, 250.0);
    let r = run(&spec);
    assert!(r.nuclei.is_empty());
    assert_eq!(r.boundaries, vec![r.region.start, r.region.end]);
}

/// The Task 9 utterance: 3-1-4 spoken with a dipping [2, 1, 4], a high level [5, 5] and a full
/// fall [5, 1], 60 ms apart.
fn dipping_utterance() -> SynthSpec {
    with_chao(
        vec![vec![2.0, 1.0, 4.0], vec![5.0, 5.0], vec![5.0, 1.0]],
        60.0,
        0.0,
    )
}

#[test]
fn dipping_contours_give_one_nucleus_and_the_edges_per_syllable_with_exact_voicing() {
    let s = synth(&dipping_utterance());
    let r = run_with(s.clone(), truth_track(&s));
    assert_eq!(r.nuclei.len(), 3, "nuclei {:?}", r.nuclei);
    for (k, n) in r.nuclei.iter().enumerate() {
        let (a, b) = s.syllable_frames[k];
        assert!(
            (a..b).contains(&n.frame),
            "nucleus {k} at {} not in {a}..{b}",
            n.frame
        );
    }
    // Every syllable start and end has a candidate within 2 frames.
    for &(a, b) in &s.syllable_frames {
        for edge in [a, b] {
            assert!(
                r.boundaries.iter().any(|&x| x.abs_diff(edge) <= 2),
                "no boundary near syllable edge {edge}: {:?}",
                r.boundaries
            );
        }
    }
}

#[test]
fn dipping_utterance_under_real_pyin_has_three_nuclei_and_every_syllable_edge() {
    // The Task 9 utterance with the f0 track production feeds this crate. pYIN's `voiced_p` sags
    // below 0.5 through the fast fall of [5, 1] although `hz` is right; nuclei (R27) look at `hz`
    // near the peak, and pause edges come from the energy, so all three syllables are found and
    // every syllable start and end has a candidate.
    let r = run(&dipping_utterance());
    let frames = r.synth.syllable_frames.clone();
    let owners: Vec<Option<usize>> = r
        .nuclei
        .iter()
        .map(|n| frames.iter().position(|&(a, b)| (a..b).contains(&n.frame)))
        .collect();
    assert_eq!(
        owners,
        vec![Some(0), Some(1), Some(2)],
        "nuclei {:?} for syllables {frames:?}",
        r.nuclei
    );
    for &(a, b) in &frames {
        for edge in [a, b] {
            assert!(
                r.boundaries.iter().any(|&x| x.abs_diff(edge) <= 2),
                "no boundary near syllable edge {edge}: {:?}",
                r.boundaries
            );
        }
    }
    assert!(r.boundaries.len() <= 4 * r.nuclei.len() + 2);
}

// --- Boundaries --------------------------------------------------------------------------------

#[test]
fn boundaries_are_edges_and_the_minimum_between_nuclei() {
    let e = two_peaks(-20.0, -22.0, -50.0);
    let region = range(12, 60);
    let ns = [nuc(20), nuc(40)];
    // No voicing changes, no span over 35 frames: the edges, the valley (frame 30) and, since R27,
    // frame 47, the last loud frame of the falling flank (threshold p10 + 10 = -50 dB).
    let b = boundaries(&e, &all_voiced(100), &region, &ns);
    assert_eq!(b, vec![12, 30, 47, 60]);
}

#[test]
fn minimum_between_nuclei_is_the_middle_of_a_flat_floor() {
    // Digital silence between syllables is a flat run of the minimum: pick its middle.
    let e = curve(
        100,
        &[
            (0, -100.0),
            (10, -100.0),
            (20, -20.0),
            (30, -100.0),
            (50, -100.0),
            (60, -20.0),
            (70, -100.0),
            (99, -100.0),
        ],
    );
    let b = boundaries(&e, &all_voiced(100), &range(10, 70), &[nuc(20), nuc(60)]);
    // The floor's middle (40), plus (R27) the last loud frame before the silence and the first
    // after it (29 and 52).
    assert_eq!(b.len(), 5, "{b:?}");
    assert!(b[2].abs_diff(40) <= 2, "{b:?}");
    assert!(b[1].abs_diff(30) <= 2 && b[3].abs_diff(51) <= 2, "{b:?}");
}

#[test]
fn voicing_crossings_are_boundaries() {
    let e = two_peaks(-20.0, -22.0, -50.0);
    let mut vp = vec![0.0; 100];
    vp[20..40].fill(0.9); // voiced 20..40: onset at frame 20, offset at frame 40
    let b = boundaries(&e, &voicing(&vp), &range(12, 60), &[nuc(20), nuc(40)]);
    assert_eq!(b, vec![12, 20, 30, 40, 47, 60]); // 47: pause edge (R27)
}

#[test]
fn voicing_edges_follow_the_pitch_not_voiced_p() {
    // R32: a frame is voiced when it has a pitch. Pitched 20..40 throughout, but voiced_p sags to
    // 0.2 over 25..33 (as pYIN's does through a fast fall): no edge there. Then 52..56 is pitched at
    // voiced_p 0.3: its edges count, as the pitch appears and disappears. (47 is the pause edge.)
    let e = two_peaks(-20.0, -22.0, -50.0);
    let frames: Vec<F0Frame> = (0..100)
        .map(|i| match i {
            25..33 => F0Frame {
                hz: Some(150.0),
                voiced_p: 0.2,
            },
            20..40 => F0Frame {
                hz: Some(150.0),
                voiced_p: 0.9,
            },
            52..56 => F0Frame {
                hz: Some(150.0),
                voiced_p: 0.3,
            },
            _ => F0Frame {
                hz: None,
                voiced_p: 0.0,
            },
        })
        .collect();
    let f0 = F0Track {
        provider: "hand".into(),
        frames,
    };
    let b = boundaries(&e, &f0, &range(12, 60), &[nuc(20), nuc(40)]);
    assert_eq!(b, vec![12, 20, 30, 40, 47, 52, 56, 60], "{b:?}");
}

#[test]
fn voicing_crossings_outside_the_region_are_ignored() {
    let e = two_peaks(-20.0, -22.0, -50.0);
    let mut vp = vec![0.0; 100];
    vp[5..8].fill(0.9);
    vp[70..80].fill(0.9);
    let b = boundaries(&e, &voicing(&vp), &range(12, 60), &[nuc(20), nuc(40)]);
    assert_eq!(b, vec![12, 30, 47, 60]); // 47: pause edge (R27), not a voicing edge
}

#[test]
fn boundaries_within_two_frames_are_deduplicated_favouring_priority() {
    let e = two_peaks(-20.0, -22.0, -50.0);
    // Voicing edges at 31 (1 frame from the valley) and 58 (2 frames from the region end): both
    // lose to the higher-priority boundary. An edge at 27 (3 frames away) survives.
    let mut vp = vec![0.0; 100];
    vp[..27].fill(1.0);
    vp[27..31].fill(0.0);
    vp[31..58].fill(1.0);
    let b = boundaries(&e, &voicing(&vp), &range(12, 60), &[nuc(20), nuc(40)]);
    assert!(
        b.contains(&12) && b.contains(&30) && b.contains(&60),
        "{b:?}"
    );
    assert!(!b.contains(&31) && !b.contains(&58), "{b:?}");
    assert!(b.contains(&27), "{b:?}");
    assert!(b.windows(2).all(|w| w[1] - w[0] > 2), "{b:?}");
}

#[test]
fn long_spans_get_interior_minima() {
    // One nucleus, an 80-frame region with a dip at 45: the span is > 35 frames so the dip is a
    // candidate; the same dip in a 30-frame region is not.
    let e = curve(
        100,
        &[
            (0, -60.0),
            (5, -30.0),
            (20, -20.0),
            (45, -35.0),
            (60, -25.0),
            (85, -30.0),
            (99, -60.0),
        ],
    );
    let b = boundaries(&e, &all_voiced(100), &range(5, 85), &[nuc(20)]);
    assert!(b.contains(&45), "{b:?}");
    assert!(b.first() == Some(&5) && b.last() == Some(&85));

    let short = curve(
        100,
        &[
            (0, -60.0),
            (5, -30.0),
            (10, -20.0),
            (17, -35.0),
            (24, -25.0),
            (35, -60.0),
        ],
    );
    let b = boundaries(&short, &all_voiced(100), &range(5, 35), &[nuc(10)]);
    // Nothing at the dip near 17; 31 is the last loud frame before the energy leaves speech (R27).
    assert_eq!(b, vec![5, 31, 35]);
}

#[test]
fn spans_are_measured_between_the_boundaries_found_so_far() {
    // One nucleus, region 5..85 with energy valleys at 30 and 72. A voicing edge cuts the region
    // in two, and a span needs to be *longer than* 35 frames to be searched for minima.
    let e = curve(
        100,
        &[
            (0, -60.0),
            (5, -30.0),
            (20, -20.0),
            (30, -33.0),
            (60, -25.0),
            (72, -34.0),
            (85, -30.0),
            (99, -60.0),
        ],
    );
    let near = |b: &[u32], at: u32| b.iter().any(|&x| x.abs_diff(at) <= 2);
    let cut_at = |edge: usize| {
        let mut vp = vec![1.0; 100];
        vp[edge..].fill(0.0);
        boundaries(&e, &voicing(&vp), &range(5, 85), &[nuc(20)])
    };

    // Edge at 45: spans of 40 and 40 frames, so both valleys are candidates.
    let b = cut_at(45);
    assert!(b.contains(&45), "{b:?}");
    assert!(near(&b, 30) && near(&b, 72), "{b:?}");

    // Edge at 40: spans of exactly 35 (not searched) and 45 (searched).
    let b = cut_at(40);
    assert!(b.contains(&40), "{b:?}");
    assert!(!near(&b, 30), "{b:?}");
    assert!(near(&b, 72), "{b:?}");
}

#[test]
fn cap_keeps_edges_and_valleys_ahead_of_voicing_flutter() {
    // Two nuclei allow 10 boundaries. A flickering voiced_p offers ~40 crossings; the two region
    // edges and the valley must survive.
    let e = two_peaks(-20.0, -22.0, -50.0);
    let vp: Vec<f32> = (0..100)
        .map(|i| if i % 3 == 0 { 0.9 } else { 0.1 })
        .collect();
    let b = boundaries(&e, &voicing(&vp), &range(12, 60), &[nuc(20), nuc(40)]);
    assert!(b.len() <= 10, "{b:?}");
    assert!(
        b.contains(&12) && b.contains(&60) && b.contains(&30),
        "{b:?}"
    );
}

#[test]
fn cap_ranks_voicing_edges_by_size_of_the_jump() {
    // One nucleus: 6 boundaries at most = 2 edges + 4 voicing crossings. Six crossings are on
    // offer, 6 frames apart, with jumps of 0.1 ... 0.6; the four biggest must be kept.
    let e = curve(100, &[(0, -60.0), (5, -20.0), (95, -20.0), (99, -60.0)]);
    let mut vp = vec![0.0_f32; 100];
    // Each crossing i goes from 0.45 to 0.45 + jump (or back), so all of them cross 0.5.
    let jumps = [0.1_f32, 0.6, 0.2, 0.5, 0.3, 0.4];
    for (k, jump) in jumps.iter().enumerate() {
        let at = 15 + 12 * k;
        // Low at 0.5 - jump/2, high at 0.5 + jump/2 alternately; the crossing frame is `at`.
        let (lo, hi) = (0.5 - jump / 2.0 - 0.001, 0.5 + jump / 2.0);
        let (before, after) = if k % 2 == 0 { (lo, hi) } else { (hi, lo) };
        for v in &mut vp[at - 6..at] {
            *v = before;
        }
        for v in &mut vp[at..at + 6] {
            *v = after;
        }
    }
    let b = boundaries(&e, &voicing(&vp), &range(5, 95), &[nuc(50)]);
    let interior: Vec<u32> = b[1..b.len() - 1].to_vec();
    // Crossings at 15 + 12k; the four biggest jumps are k = 1 (0.6), 3 (0.5), 5 (0.4), 4 (0.3).
    assert_eq!(interior, vec![27, 51, 63, 75], "{b:?}");
}

#[test]
fn interior_minima_are_last_in_priority() {
    // 1 nucleus -> cap 6. Voicing crossings alone fill the four free slots, so a deep interior
    // minimum in a long span gets no room.
    let e = curve(
        200,
        &[
            (0, -60.0),
            (5, -20.0),
            (60, -45.0),
            (90, -20.0),
            (150, -20.0),
            (199, -60.0),
        ],
    );
    let mut vp = vec![0.9_f32; 200];
    for k in 0..4 {
        // Four separate unvoiced dips of width 4 -> 8 crossings, far more than fit.
        let at = 20 + 25 * k;
        vp[at..at + 4].fill(0.1);
    }
    let b = boundaries(&e, &voicing(&vp), &range(5, 150), &[nuc(90)]);
    assert!(b.len() <= 6, "{b:?}");
    assert!(!b.contains(&60), "{b:?}");
}

/// Two 20-frame loud stretches (10..30 and 60..80) with silence between them.
fn loud_pause_loud() -> EnergyTrack {
    curve(
        100,
        &[
            (0, -60.0),
            (9, -60.0),
            (12, -20.0),
            (28, -20.0),
            (31, -60.0),
            (59, -60.0),
            (62, -20.0),
            (78, -20.0),
            (81, -60.0),
            (99, -60.0),
        ],
    )
}

#[test]
fn pause_edges_are_boundaries_whatever_the_voicing() {
    // R27: where the smoothed dB leaves and re-enters speech inside the region. No pitch at all.
    let e = loud_pause_loud();
    let b = boundaries(
        &e,
        &voicing(&[0.0; 100]),
        &range(10, 80),
        &[nuc(20), nuc(70)],
    );
    let near = |at: u32| b.iter().any(|&x| x.abs_diff(at) <= 2);
    assert!(near(30) && near(60), "{b:?}");
    assert_eq!(b.first(), Some(&10));
    assert_eq!(b.last(), Some(&80));
}

#[test]
fn pause_edges_outrank_voicing_edges_under_the_cap() {
    // One nucleus allows 6 boundaries: 2 region edges, then the pause edges, then voicing edges.
    // Voicing flickers on 12..28 with plenty of big crossings that must not push them out.
    let e = loud_pause_loud();
    let vp: Vec<f32> = (0..100)
        .map(|i| {
            if (12..28).contains(&i) && i % 3 == 0 {
                0.9
            } else {
                0.1
            }
        })
        .collect();
    let b = boundaries(&e, &voicing(&vp), &range(10, 80), &[nuc(20)]);
    assert!(b.len() <= 6, "{b:?}");
    let near = |at: u32| b.iter().any(|&x| x.abs_diff(at) <= 2);
    assert!(near(30) && near(60), "{b:?}");
}

#[test]
fn boundaries_with_uses_the_callers_speech_margin() {
    // With a margin of 50 dB nothing in this track is speech, so there are no pause edges;
    // `boundaries` itself uses the default 10 dB.
    let e = loud_pause_loud();
    let f0 = all_voiced(100);
    let ns = [nuc(20), nuc(70)];
    let strict = SegmentParams {
        speech_margin_db: 50.0,
        ..Default::default()
    };
    let b = boundaries_with(&e, &f0, &range(10, 80), &ns, &strict);
    assert_eq!(b.len(), 3, "{b:?}"); // edges and the floor between the nuclei
    let b = boundaries_with(&e, &f0, &range(10, 80), &ns, &SegmentParams::default());
    assert_eq!(b, boundaries(&e, &f0, &range(10, 80), &ns));
    assert!(b.len() > 3, "{b:?}");
}

#[test]
fn degenerate_regions_still_report_their_edges() {
    let e = EnergyTrack {
        db: vec![-30.0; 50],
    };
    assert_eq!(
        boundaries(&e, &all_voiced(50), &range(10, 10), &[]),
        vec![10]
    );
    assert_eq!(
        boundaries(&e, &all_voiced(50), &range(10, 12), &[]),
        vec![10, 12]
    );
    assert_eq!(
        boundaries(&e, &all_voiced(50), &range(10, 40), &[]),
        vec![10, 40]
    );
}

// --- Properties over arbitrary tracks ----------------------------------------------------------

proptest! {
    #![proptest_config(ProptestConfig::with_cases(128))]

    #[test]
    fn invariants_hold_on_arbitrary_tracks(
        db in proptest::collection::vec(-100.0_f32..0.0, 1..300),
        vp_seed in proptest::collection::vec(0.0_f32..1.0, 1..300),
        margin in 0.0_f32..20.0,
        dip in 0.0_f32..6.0,
        gap in 1_u32..12,
    ) {
        let len = db.len();
        let vp: Vec<f32> = (0..len).map(|i| vp_seed[i % vp_seed.len()]).collect();
        let e = EnergyTrack { db };
        let f0 = voicing(&vp);
        let p = SegmentParams { speech_margin_db: margin, dip_db: dip, min_nucleus_gap: gap };
        let Some(region) = speech_region(&e, &p) else { return Ok(()); };
        prop_assert!(region.start < region.end && region.end as usize <= len);

        let ns = nuclei(&e, &f0, &region, &p);
        for n in &ns {
            prop_assert!(n.frame >= region.start && n.frame < region.end);
            let f = n.frame as usize;
            prop_assert!((f.saturating_sub(2)..=(f + 2).min(len - 1)).any(|i| vp[i] >= 0.5));
            prop_assert!(n.strength_db >= margin - 1e-3);
        }
        for w in ns.windows(2) {
            prop_assert!(w[1].frame >= w[0].frame + gap, "spacing {w:?}");
        }

        let b = boundaries(&e, &f0, &region, &ns);
        prop_assert!(b.len() <= 4 * ns.len() + 2, "{} boundaries, {} nuclei", b.len(), ns.len());
        prop_assert_eq!(b.first().copied(), Some(region.start));
        prop_assert_eq!(b.last().copied(), Some(region.end));
        prop_assert!(b.iter().all(|&x| x >= region.start && x <= region.end));
        prop_assert!(b.windows(2).all(|w| w[0] < w[1]), "sorted and unique {b:?}");
        if region.end - region.start > 2 {
            prop_assert!(b.windows(2).all(|w| w[1] - w[0] > 2), "dedup {b:?}");
        }
    }

    #[test]
    fn boundaries_are_capped_for_any_nuclei_and_region(
        db in proptest::collection::vec(-100.0_f32..0.0, 1..200),
        vp_seed in proptest::collection::vec(0.0_f32..1.0, 1..200),
        nuclei_at in proptest::collection::vec(0_u32..200, 0..8),
        a in 0_u32..200,
        b in 0_u32..200,
    ) {
        let len = db.len() as u32;
        let vp: Vec<f32> = (0..len as usize).map(|i| vp_seed[i % vp_seed.len()]).collect();
        let (start, end) = (a.min(b).min(len), a.max(b).min(len));
        let ns: Vec<Nucleus> = nuclei_at.iter().map(|&f| nuc(f % len)).collect();
        let out = boundaries(&EnergyTrack { db }, &voicing(&vp), &range(start, end), &ns);
        prop_assert!(out.len() <= 4 * ns.len() + 2);
        prop_assert!(out.contains(&start) && out.contains(&end));
        prop_assert!(out.windows(2).all(|w| w[0] < w[1]));
    }
}
