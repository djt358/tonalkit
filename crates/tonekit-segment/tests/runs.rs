//! Rulings R58 and R59: voiced runs separate syllables when the level does not, if the pitch
//! breaks between them.

use tonekit_core::{EnergyTrack, F0Frame, F0Track, FrameRange};
use tonekit_segment::{boundaries, nuclei, speech_region, SegmentParams};

/// 100 frames: silence, then a perfectly flat level on 20..80, then silence.
fn flat() -> EnergyTrack {
    EnergyTrack {
        db: (0..100)
            .map(|i| if (20..80).contains(&i) { -12.0 } else { -90.0 })
            .collect(),
    }
}

/// 100 frames with the pitch `hz(i)` (`None`: unvoiced).
fn track(hz: impl Fn(usize) -> Option<f32>) -> F0Track {
    F0Track {
        provider: "hand".into(),
        frames: (0..100)
            .map(|i| F0Frame {
                hz: hz(i),
                voiced_p: 0.9,
            })
            .collect(),
    }
}

/// Voiced at 150 Hz wherever `voiced(i)`.
fn pitched(voiced: impl Fn(usize) -> bool) -> F0Track {
    track(|i| voiced(i).then_some(150.0))
}

/// `hz` raised by `st` semitones.
fn up(hz: f32, st: f32) -> f32 {
    hz * 2f32.powf(st / 12.0)
}

fn region(e: &EnergyTrack) -> FrameRange {
    speech_region(e, &SegmentParams::default()).unwrap()
}

fn frames(e: &EnergyTrack, f0: &F0Track) -> Vec<u32> {
    nuclei(e, f0, &region(e), &SegmentParams::default())
        .iter()
        .map(|n| n.frame)
        .collect()
}

#[test]
fn a_flat_level_with_three_pitch_breaks_is_three_nuclei_each_inside_its_run() {
    // Runs 20..38 (120 Hz), 41..58 (5 st up) and 62..80 (4 st down from that): breaks of 3 and 4
    // unvoiced frames, no dip anywhere.
    let e = flat();
    let f0 = track(|i| match i {
        20..=37 => Some(120.0),
        41..=57 => Some(up(120.0, 5.0)),
        62..=79 => Some(up(120.0, 1.0)),
        _ => None,
    });
    let found = frames(&e, &f0);
    assert_eq!(found.len(), 3, "{found:?}");
    for (n, run) in found.iter().zip([20..38, 41..58, 62..80]) {
        assert!(run.contains(n), "{n} outside {run:?}");
    }
}

#[test]
fn a_two_frame_dropout_is_bridged_and_stays_one_nucleus() {
    let e = flat();
    let f0 = pitched(|i| (20..48).contains(&i) || (50..80).contains(&i));
    assert_eq!(frames(&e, &f0).len(), 1);
}

#[test]
fn a_short_run_never_holds_a_nucleus_of_its_own() {
    // 20..50 and a 4-frame run at 60..64 (less than 5 voiced frames).
    let e = flat();
    let f0 = pitched(|i| (20..50).contains(&i) || (60..64).contains(&i));
    assert_eq!(frames(&e, &f0).len(), 1);
}

#[test]
fn on_a_flat_level_the_boundary_between_runs_is_the_pitch_break() {
    // R59: the edges of the break (38: the first unvoiced frame; 41: the next run's first voiced
    // frame), not some frame of the flat level.
    let e = flat();
    let f0 = track(|i| match i {
        20..=37 => Some(120.0),
        41..=79 => Some(up(120.0, 4.0)),
        _ => None,
    });
    let r = region(&e);
    let ns = nuclei(&e, &f0, &r, &SegmentParams::default());
    assert_eq!(ns.len(), 2);
    let b = boundaries(&e, &f0, &r, &ns);
    assert!(b.contains(&38) && b.contains(&41), "{b:?}");
    let between: Vec<u32> = b
        .iter()
        .copied()
        .filter(|&x| ns[0].frame < x && x < ns[1].frame)
        .collect();
    assert_eq!(between, vec![38, 41], "{b:?}");
}

#[test]
fn a_peak_just_outside_a_run_moves_onto_it() {
    // A level peaking at frame 30, voiced only from 32: the nucleus is the run's first frame.
    let e = EnergyTrack {
        db: (0..100)
            .map(|i| match i {
                20..=29 => -30.0 + (i - 20) as f32 * 2.0,
                30..=60 => -10.0 - (i - 30) as f32 * 0.2,
                _ => -90.0,
            })
            .collect(),
    };
    let f0 = pitched(|i| (32..60).contains(&i));
    let found = frames(&e, &f0);
    assert_eq!(found, vec![32], "{found:?}");
}

#[test]
fn a_dropout_inside_one_continuous_contour_stays_one_nucleus() {
    // A creaky tone 3: falling to the floor, 3 to 8 unvoiced frames, rising from just above it
    // (under 3 semitones from where it dropped out). One nucleus, inside the voiced stretch, and
    // no pitch-break boundary between the two parts.
    let e = flat();
    for dropout in [3, 4, 6, 8] {
        let (gap_start, gap_end) = (45, 45 + dropout);
        let f0 = track(|i| {
            if !(20..80).contains(&i) || (gap_start..gap_end).contains(&i) {
                None
            } else if i < gap_start {
                Some(up(100.0, (gap_start - i) as f32 * 0.2))
            } else {
                Some(up(100.0, 2.5 + (i - gap_end) as f32 * 0.3))
            }
        });
        let r = region(&e);
        let ns = nuclei(&e, &f0, &r, &SegmentParams::default());
        assert_eq!(ns.len(), 1, "dropout {dropout}: {ns:?}");
        assert!((20..80).contains(&ns[0].frame), "{ns:?}");
        // The voicing edges of the dropout are still candidates (rule 4); nothing else is added.
        let b = boundaries(&e, &f0, &r, &ns);
        assert!(b.len() <= 4 * ns.len() + 2, "{b:?}");
    }
    // The same dropout with the pitch coming back 3 semitones or more away is a join: two.
    let f0 = track(|i| match i {
        20..=44 => Some(up(100.0, (45 - i) as f32 * 0.2)),
        49..=79 => Some(up(100.0, 3.2 + (i - 49) as f32 * 0.3)),
        _ => None,
    });
    assert_eq!(frames(&e, &f0).len(), 2);
}
