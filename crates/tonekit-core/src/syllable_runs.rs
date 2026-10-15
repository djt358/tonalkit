//! Syllable runs (ruling R58): the long voiced runs that make up one syllable's voiced part.
//!
//! In fluent speech pYIN loses the pitch for a few frames where the voice jumps from one tone to
//! the next, so a gap between two long voiced runs is the sign of a join between syllables. But it
//! also loses the pitch inside one syllable: at the creaky bottom of a tone 3 the pitch drops out
//! near the floor and comes back near it. What tells the two apart is the pitch across the gap: a
//! join moves it far (a tone 4 into a tone 1, a tone 3 into a tone 4, a tone 2 into a tone 3: 6 to
//! 15 semitones for typical speakers), a creak barely at all. One definition, shared by nucleus
//! detection, boundary candidates and shape extraction.

use std::ops::Range;

use crate::{voiced_runs, MIN_RUN_FRAMES};

/// How far, in semitones, the pitch must move across the gap between two long voiced runs (from
/// the last voiced frame before it to the first after it) for the gap to be a join between two
/// syllables rather than a dropout inside one contour (ruling R58).
pub const PITCH_BREAK_ST: f64 = 3.0;

/// One syllable's voiced part: one or more long voiced runs, each the range of positions in the
/// `frames` given to [`syllable_runs`] it covers, in order.
pub type SyllableRun = Vec<Range<usize>>;

/// The syllable runs of `frames` (indices of voiced frames, increasing) whose pitches are `st`
/// (semitones against any fixed reference, one per entry of `frames`): the long voiced runs
/// ([`voiced_runs`] with at least [`MIN_RUN_FRAMES`] voiced frames), consecutive ones grouped into
/// one syllable run where the pitch moves less than [`PITCH_BREAK_ST`] across the gap between
/// them. Short runs are in no syllable run, even between two parts of one.
///
/// # Panics
///
/// If `st` is shorter than `frames`.
pub fn syllable_runs(frames: &[usize], st: &[f64]) -> Vec<SyllableRun> {
    let mut out: Vec<SyllableRun> = Vec::new();
    for run in voiced_runs(frames)
        .into_iter()
        .filter(|r| r.len() >= MIN_RUN_FRAMES)
    {
        match out.last_mut() {
            Some(group) if !pitch_breaks(st, group[group.len() - 1].end - 1, run.start) => {
                group.push(run)
            }
            _ => out.push(vec![run]),
        }
    }
    out
}

/// Whether the pitch moves [`PITCH_BREAK_ST`] or more from position `a` to position `b` of `st`.
/// A pitch that is not a finite number counts as a break.
fn pitch_breaks(st: &[f64], a: usize, b: usize) -> bool {
    let moved = (st[b] - st[a]).abs();
    moved.is_nan() || moved >= PITCH_BREAK_ST
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Frames 0..8 at 0 st, a 4-frame dropout, 12..20 at `after` st.
    fn dropout(after: f64) -> (Vec<usize>, Vec<f64>) {
        let frames: Vec<usize> = (0..8).chain(12..20).collect();
        let st = frames
            .iter()
            .map(|&i| if i < 8 { 0.0 } else { after })
            .collect();
        (frames, st)
    }

    #[test]
    fn long_runs_are_one_syllable_unless_the_pitch_breaks_across_the_gap() {
        let (frames, st) = dropout(2.9);
        assert_eq!(syllable_runs(&frames, &st), vec![vec![0..8, 8..16]]);
        for far in [3.0, -3.0, 12.0] {
            let (frames, st) = dropout(far);
            assert_eq!(syllable_runs(&frames, &st), vec![vec![0..8], vec![8..16]]);
        }
        let (frames, st) = dropout(f64::NAN);
        assert_eq!(syllable_runs(&frames, &st), vec![vec![0..8], vec![8..16]]);
    }

    #[test]
    fn short_runs_join_nothing_and_a_break_starts_a_new_group() {
        // 0..8 (0 st), a 3-frame run 11..14 (40 st), 17..25 (1 st), 28..36 (9 st).
        let frames: Vec<usize> = (0..8).chain(11..14).chain(17..25).chain(28..36).collect();
        let st: Vec<f64> = frames
            .iter()
            .map(|&i| match i {
                0..=7 => 0.0,
                11..=13 => 40.0,
                17..=24 => 1.0,
                _ => 9.0,
            })
            .collect();
        assert_eq!(
            syllable_runs(&frames, &st),
            vec![vec![0..8, 11..19], vec![19..27]]
        );
        assert!(syllable_runs(&[], &[]).is_empty());
    }
}
