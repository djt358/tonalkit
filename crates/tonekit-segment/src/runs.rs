//! Voiced runs as syllable separators (ruling R58).
//!
//! A voiced run (ruling R32: a stretch of frames with a pitch, gaps of up to two frames bridged)
//! is roughly one syllable's voiced part, and a nucleus's tone is measured on its own run alone
//! (ruling R50). In fluent speech the level need not dip between syllables, but the pitch tracker
//! loses the pitch for a few frames where the voice moves fast from one tone to the next, so two
//! long runs are two syllables even when the energy between them is flat.

use tonekit_core::{voiced_runs, F0Track, MIN_RUN_FRAMES};

/// A long voiced run (at least [`MIN_RUN_FRAMES`] voiced frames): its first and last voiced frame.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct Run {
    pub first: usize,
    pub last: usize,
}

/// The long voiced runs of `f0`, in frame order.
pub(crate) fn long_runs(f0: &F0Track) -> Vec<Run> {
    let voiced: Vec<usize> = f0
        .frames
        .iter()
        .enumerate()
        .filter_map(|(i, f)| f.hz.is_some().then_some(i))
        .collect();
    voiced_runs(&voiced)
        .into_iter()
        .filter(|r| r.len() >= MIN_RUN_FRAMES)
        .map(|r| Run {
            first: voiced[r.start],
            last: voiced[r.end - 1],
        })
        .collect()
}

/// The index in `runs` of the long run that frame `at` belongs to: the one holding it, or else the
/// nearest within `radius` frames of it (the earlier on a tie). `None` if no long run is that
/// close.
pub(crate) fn run_of(runs: &[Run], at: usize, radius: usize) -> Option<usize> {
    runs.iter()
        .enumerate()
        .map(|(k, r)| (k, r.first.saturating_sub(at).max(at.saturating_sub(r.last))))
        .filter(|&(_, distance)| distance <= radius)
        .min_by_key(|&(k, distance)| (distance, k))
        .map(|(k, _)| k)
}

/// Whether frames `a` and `b` belong to two different long runs (each within `radius` of its run).
pub(crate) fn in_separate_runs(runs: &[Run], a: usize, b: usize, radius: usize) -> bool {
    matches!(
        (run_of(runs, a, radius), run_of(runs, b, radius)),
        (Some(x), Some(y)) if x != y
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use tonekit_core::F0Frame;

    fn track(voiced: &[bool]) -> F0Track {
        F0Track {
            frames: voiced
                .iter()
                .map(|&v| F0Frame {
                    hz: v.then_some(150.0),
                    voiced_p: if v { 0.9 } else { 0.0 },
                })
                .collect(),
            provider: "test".into(),
        }
    }

    #[test]
    fn long_runs_bridge_two_frame_gaps_and_drop_short_runs() {
        // 0..6 voiced, 6..8 gap (bridged), 8..12 voiced, 12..15 gap, 15..18 voiced (short).
        let mut v = vec![true; 18];
        for i in [6, 7, 12, 13, 14] {
            v[i] = false;
        }
        assert_eq!(long_runs(&track(&v)), vec![Run { first: 0, last: 11 }]);
        assert!(long_runs(&track(&[false; 5])).is_empty());
    }

    #[test]
    fn a_frame_belongs_to_the_run_holding_it_or_the_nearest_close_one() {
        let runs = [
            Run {
                first: 10,
                last: 20,
            },
            Run {
                first: 24,
                last: 40,
            },
        ];
        assert_eq!(run_of(&runs, 15, 2), Some(0));
        assert_eq!(run_of(&runs, 22, 2), Some(0)); // 2 from both: the earlier
        assert_eq!(run_of(&runs, 23, 2), Some(1));
        assert_eq!(run_of(&runs, 5, 2), None);
        assert!(in_separate_runs(&runs, 12, 30, 2));
        assert!(!in_separate_runs(&runs, 12, 18, 2));
        assert!(!in_separate_runs(&runs, 2, 30, 2));
    }
}
