//! Voiced runs as syllable separators (ruling R58).
//!
//! A voiced run (ruling R32: a stretch of frames with a pitch, gaps of up to two frames bridged)
//! is roughly one syllable's voiced part, and a nucleus's tone is measured on its own run alone
//! (ruling R50). In fluent speech the level need not dip between syllables, but the pitch tracker
//! loses the pitch for a few frames where the voice moves fast from one tone to the next, so two
//! long runs are two syllables even when the energy between them is flat, provided the pitch
//! breaks across the gap between them. A dropout inside one continuous contour (the creaky bottom
//! of a tone 3, where the pitch on both sides sits near the floor) is not a join: those runs are
//! one syllable run ([`tonekit_core::syllable_runs`]).

use tonekit_core::{voiced_runs, F0Track, MIN_RUN_FRAMES};

/// A peak is voiced if pYIN reports a pitch on any frame within this many frames of it (ruling
/// R27), and a frame this close to a run belongs to it.
pub(crate) const VOICING_RADIUS: usize = 2;

/// A long voiced run (at least [`MIN_RUN_FRAMES`] voiced frames), or a syllable run of several:
/// its first and last voiced frame.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct Run {
    pub first: usize,
    pub last: usize,
}

/// A gap inside one syllable run (ruling R58): the last voiced frame before it and the first
/// after it. The pitch moves less than [`tonekit_core::PITCH_BREAK_ST`] across it.
#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct Dropout {
    pub before: usize,
    pub after: usize,
}

/// The voiced frames of `f0`, in order.
fn voiced_frames(f0: &F0Track) -> Vec<usize> {
    f0.frames
        .iter()
        .enumerate()
        .filter_map(|(i, f)| f.hz.is_some().then_some(i))
        .collect()
}

/// The syllable runs of `f0` ([`tonekit_core::syllable_runs`]), each as its long runs in frame
/// order.
fn syllable_parts(f0: &F0Track) -> Vec<Vec<Run>> {
    let voiced = voiced_frames(f0);
    // Semitones against 1 Hz: only differences are compared. A pitch that is not a positive
    // finite number reads as NaN, which counts as a break.
    let st: Vec<f64> = voiced
        .iter()
        .map(|&i| match f0.frames[i].hz {
            Some(hz) if hz.is_finite() && hz > 0.0 => 12.0 * f64::from(hz).log2(),
            _ => f64::NAN,
        })
        .collect();
    tonekit_core::syllable_runs(&voiced, &st)
        .into_iter()
        .map(|group| {
            group
                .into_iter()
                .map(|r| Run {
                    first: voiced[r.start],
                    last: voiced[r.end - 1],
                })
                .collect()
        })
        .collect()
}

/// The syllable runs of `f0` (ruling R58), each from its first part's first voiced frame to its
/// last part's last, in frame order. Two nuclei in different syllable runs are two syllables even
/// on a flat level.
pub(crate) fn syllable_runs(f0: &F0Track) -> Vec<Run> {
    syllable_parts(f0)
        .into_iter()
        .map(|parts| Run {
            first: parts[0].first,
            last: parts[parts.len() - 1].last,
        })
        .collect()
}

/// The gaps inside the syllable runs of `f0` (ruling R58: dropouts within one contour, such as a
/// creaky tone 3's bottom), in frame order.
pub(crate) fn dropouts(f0: &F0Track) -> Vec<Dropout> {
    syllable_parts(f0)
        .into_iter()
        .flat_map(|parts| {
            parts
                .windows(2)
                .map(|w| Dropout {
                    before: w[0].last,
                    after: w[1].first,
                })
                .collect::<Vec<_>>()
        })
        .collect()
}

/// The long voiced runs of `f0`, in frame order.
pub(crate) fn long_runs(f0: &F0Track) -> Vec<Run> {
    let voiced = voiced_frames(f0);
    voiced_runs(&voiced)
        .into_iter()
        .filter(|r| r.len() >= MIN_RUN_FRAMES)
        .map(|r| Run {
            first: voiced[r.start],
            last: voiced[r.end - 1],
        })
        .collect()
}

/// The index in `runs` of the run that frame `at` belongs to: the one holding it, or else the
/// nearest within `radius` frames of it (the earlier on a tie). `None` if no run is that
/// close.
pub(crate) fn run_of(runs: &[Run], at: usize, radius: usize) -> Option<usize> {
    runs.iter()
        .enumerate()
        .map(|(k, r)| (k, r.first.saturating_sub(at).max(at.saturating_sub(r.last))))
        .filter(|&(_, distance)| distance <= radius)
        .min_by_key(|&(k, distance)| (distance, k))
        .map(|(k, _)| k)
}

/// Whether frames `a` and `b` belong to two different runs (each within `radius` of its run).
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

    fn track_hz(hz: &[Option<f32>]) -> F0Track {
        F0Track {
            frames: hz
                .iter()
                .map(|&h| F0Frame {
                    hz: h,
                    voiced_p: if h.is_some() { 0.9 } else { 0.0 },
                })
                .collect(),
            provider: "test".into(),
        }
    }

    #[test]
    fn long_runs_join_into_one_syllable_run_unless_the_pitch_breaks_across_the_gap() {
        // 0..8 at 100 Hz, a 4-frame dropout, 12..20 at `after` Hz.
        let at = |after: f32| -> Vec<Option<f32>> {
            (0..20)
                .map(|i| match i {
                    0..=7 => Some(100.0),
                    12..=19 => Some(after),
                    _ => None,
                })
                .collect()
        };
        // 2.9 semitones up (a creaky bottom coming back): one stretch.
        let near = 100.0 * 2f32.powf(2.9 / 12.0);
        assert_eq!(
            syllable_runs(&track_hz(&at(near))),
            vec![Run { first: 0, last: 19 }]
        );
        assert_eq!(
            dropouts(&track_hz(&at(near))),
            vec![Dropout {
                before: 7,
                after: 12
            }]
        );
        // 3.1 semitones either way (a join between two tones): two.
        for far in [
            100.0 * 2f32.powf(3.1 / 12.0),
            100.0 * 2f32.powf(-3.1 / 12.0),
        ] {
            assert_eq!(
                syllable_runs(&track_hz(&at(far))),
                vec![
                    Run { first: 0, last: 7 },
                    Run {
                        first: 12,
                        last: 19
                    }
                ]
            );
            assert!(dropouts(&track_hz(&at(far))).is_empty());
        }
        // Three runs, the middle one continuous with the first and broken from the third.
        let mut hz = at(100.0);
        hz.extend((0..4).map(|_| None));
        hz.extend((0..8).map(|_| Some(200.0)));
        assert_eq!(
            syllable_runs(&track_hz(&hz)),
            vec![
                Run { first: 0, last: 19 },
                Run {
                    first: 24,
                    last: 31
                }
            ]
        );
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
