//! Rulings R58 and R59: voiced runs separate syllables when the level does not.

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

fn pitched(voiced: impl Fn(usize) -> bool) -> F0Track {
    F0Track {
        provider: "hand".into(),
        frames: (0..100)
            .map(|i| F0Frame {
                hz: voiced(i).then_some(150.0),
                voiced_p: 0.9,
            })
            .collect(),
    }
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
    // Runs 20..38, 41..58, 62..80: breaks of 3 and 4 unvoiced frames, no dip anywhere.
    let e = flat();
    let f0 = pitched(|i| (20..38).contains(&i) || (41..58).contains(&i) || (62..80).contains(&i));
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
    let f0 = pitched(|i| (20..38).contains(&i) || (41..80).contains(&i));
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
