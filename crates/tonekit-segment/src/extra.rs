//! Syllable candidates beyond the nuclei (ruling R102), for a reading with more syllables than the
//! nuclei can hold.
//!
//! The nuclei (R27, R58) are the syllables the segmenter is sure of: energy peaks with a pitch.
//! Two kinds of syllable escape them. A vowel can be loud and vowel-like but have no pitch the
//! tracker accepts (a creaky or breathy vowel, most often a phrase-final tone 3); and two syllables
//! joined by a sonorant (只猫 zhī māo) can run as one voiced run with no dip and no pitch break, so
//! they hold one nucleus. When a card has more syllables than the nuclei can hold, the decoder may
//! also use these candidates (ruling R102); otherwise they play no part.

use tonekit_core::{EnergyTrack, F0Track, FrameRange, Nucleus};

use crate::region::floor_db;
use crate::runs::{long_runs, VOICING_RADIUS};
use crate::smooth::{argmin_middle, frame, shallow_valley, smoothed_db};
use crate::split::split;
use crate::unpitched::unpitched_peaks;
use crate::SegmentParams;

/// Syllable candidates the nuclei miss, and the boundary candidates that go with them.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct ExtraCandidates {
    /// One frame per candidate syllable, sorted; `strength_db` as for nuclei.
    pub nuclei: Vec<Nucleus>,
    /// The edges they need, sorted and unique (they may repeat the analysis's boundaries).
    pub boundaries: Vec<u32>,
}

/// The syllable candidates of `region` that `nuclei` miss (ruling R102).
///
/// - **Unpitched syllables.** A local maximum of the smoothed level (as for nuclei) at or above the
///   speech threshold, with no pitch on any frame within 2 of it and a vowel's spectrum there
///   (mean sonority over those frames at least `SONORANT_SHARE`), is a syllable whose pitch was
///   lost. These peaks and the nuclei are merged left to right by the nucleus rule (R27): closer
///   than `min_nucleus_gap`, or a valley no deeper than `dip_db` below the lower peak, is one
///   syllable; a nucleus always survives a merge, and of two unpitched peaks the louder (the
///   earlier on a tie). Each surviving peak is a candidate, with a boundary at the level's minimum
///   (the middle of a flat one) between it and each neighbouring nucleus or candidate.
/// - **Joined syllables.** A long voiced run (R58) holding exactly one nucleus (within 2 frames) may
///   hold a second syllable joined to it with no dip and no pitch break: if its sonority changes by
///   0.2 or more across some frame at least 6 frames from both ends of the run and 3 from the
///   nucleus, the frame where it changes most splits the run; the candidate is the middle of the
///   part without the nucleus (its loudest frame tends to sit at the join, where an analysis
///   boundary often already cuts the part short), with a boundary at the split.
///
/// Without a sonority track as long as the energy track (an analysis made before it existed),
/// there are no candidates.
pub fn extra_candidates(
    e: &EnergyTrack,
    f0: &F0Track,
    sonority: &[f32],
    region: &FrameRange,
    nuclei: &[Nucleus],
    p: &SegmentParams,
) -> ExtraCandidates {
    let n = e.db.len();
    let Some(floor) = floor_db(e) else {
        return ExtraCandidates::default();
    };
    if sonority.len() != n || f0.frames.len() != n {
        return ExtraCandidates::default();
    }
    let s = smoothed_db(&e.db);
    let threshold = floor + p.speech_margin_db;
    let (start, end) = (region.start as usize, (region.end as usize).min(n));
    let speech_at = |i: usize| (start..end).contains(&i) && s[i] >= threshold;

    let mut anchors: Vec<(usize, bool)> = nuclei
        .iter()
        .map(|x| (x.frame as usize, true))
        .filter(|&(f, _)| f < n)
        .chain(
            unpitched_peaks(&s, f0, sonority, start, end, speech_at)
                .into_iter()
                .map(|f| (f, false)),
        )
        .collect();
    anchors.sort_unstable();
    anchors.dedup_by_key(|x| x.0);
    let kept = merged(anchors, &s, p);

    let strength = |at: usize| s[at] - floor;
    let mut out = ExtraCandidates::default();
    for (k, &(at, is_nucleus)) in kept.iter().enumerate() {
        if is_nucleus {
            continue;
        }
        out.nuclei.push(Nucleus {
            frame: frame(at),
            strength_db: strength(at),
        });
        if k > 0 {
            out.boundaries
                .push(frame(argmin_middle(&s, kept[k - 1].0, at)));
        }
        if let Some(&(next, _)) = kept.get(k + 1) {
            out.boundaries.push(frame(argmin_middle(&s, at, next)));
        }
    }

    let held: Vec<usize> = kept.iter().map(|&(f, _)| f).collect();
    for run in long_runs(f0) {
        let inside: Vec<usize> = held
            .iter()
            .copied()
            .filter(|&f| f + VOICING_RADIUS >= run.first && f <= run.last + VOICING_RADIUS)
            .collect();
        let [nucleus] = inside.as_slice() else {
            continue;
        };
        if let Some(k) = split(sonority, run.first, run.last, *nucleus) {
            let (lo, hi) = if *nucleus < k {
                (k, run.last)
            } else {
                (run.first, k - 1)
            };
            let middle = (lo + hi) / 2;
            out.nuclei.push(Nucleus {
                frame: frame(middle),
                strength_db: strength(middle),
            });
            out.boundaries.push(frame(k));
        }
    }

    out.nuclei.sort_by_key(|x| x.frame);
    out.boundaries.sort_unstable();
    out.boundaries.dedup();
    out
}

/// `anchors` (sorted `(frame, is_nucleus)`) merged left to right: one closer than
/// `min_nucleus_gap` to the one kept before it, or with a shallow valley between them, is one
/// syllable with it. A nucleus survives a merge; of two unpitched peaks the louder does (the
/// earlier on a tie). A survivor is compared with the one before it in turn.
fn merged(anchors: Vec<(usize, bool)>, s: &[f32], p: &SegmentParams) -> Vec<(usize, bool)> {
    let mut kept: Vec<(usize, bool)> = Vec::new();
    for mut current in anchors {
        while let Some(&prev) = kept.last() {
            let close = current.0 - prev.0 < p.min_nucleus_gap as usize;
            if !(close || shallow_valley(s, prev.0, current.0, p.dip_db)) {
                break;
            }
            // Two nuclei never merge here: the segmenter already kept both.
            if prev.1 && current.1 {
                break;
            }
            kept.pop();
            let current_wins = match (prev.1, current.1) {
                (false, true) => true,
                (true, false) => false,
                _ => s[current.0] > s[prev.0],
            };
            if !current_wins {
                current = prev;
            }
        }
        kept.push(current);
    }
    kept
}

#[cfg(test)]
mod tests {
    use super::*;
    use tonekit_core::F0Frame;

    fn track(hz: impl Fn(usize) -> Option<f32>, n: usize) -> F0Track {
        F0Track {
            provider: "hand".into(),
            frames: (0..n)
                .map(|i| F0Frame {
                    hz: hz(i),
                    voiced_p: 0.9,
                })
                .collect(),
        }
    }

    fn level(db: impl Fn(usize) -> f32, n: usize) -> EnergyTrack {
        EnergyTrack {
            db: (0..n).map(db).collect(),
        }
    }

    fn nucleus(frame: u32) -> Nucleus {
        Nucleus {
            frame,
            strength_db: 20.0,
        }
    }

    fn frames(x: &ExtraCandidates) -> Vec<u32> {
        x.nuclei.iter().map(|c| c.frame).collect()
    }

    const N: usize = 100;
    const REGION: FrameRange = FrameRange { start: 10, end: 90 };

    /// A pitched syllable on 20..40 (nucleus at 30), a fricative on 45..55, then a loud stretch on
    /// 55..80 with no pitch, peaking at 66; `vowel` is its sonority (the fricative's is 0.05).
    fn creaky_third(vowel: f32) -> (EnergyTrack, F0Track, Vec<f32>) {
        let e = level(
            |i| match i {
                20..=39 => -20.0,
                45..=54 => -30.0,
                55..=79 => -26.0 + 3.0 * (1.0 - (i as f32 - 66.0).abs() / 11.0),
                _ => -80.0,
            },
            N,
        );
        let f0 = track(|i| (20..40).contains(&i).then_some(200.0), N);
        let son = (0..N)
            .map(|i| match i {
                45..=54 => 0.05,
                55..=79 => vowel,
                _ => 0.8,
            })
            .collect();
        (e, f0, son)
    }

    #[test]
    fn a_loud_vowel_like_peak_without_a_pitch_is_a_candidate() {
        let (e, f0, son) = creaky_third(0.8);
        let x = extra_candidates(
            &e,
            &f0,
            &son,
            &REGION,
            &[nucleus(30)],
            &SegmentParams::default(),
        );
        assert_eq!(frames(&x), vec![66]);
        // One boundary between it and the nucleus, in the dip before the fricative.
        assert_eq!(x.boundaries.len(), 1, "{x:?}");
        assert!((40..55).contains(&x.boundaries[0]), "{x:?}");
    }

    #[test]
    fn a_fricative_or_noise_is_no_syllable() {
        let (e, f0, son) = creaky_third(0.15);
        let x = extra_candidates(
            &e,
            &f0,
            &son,
            &REGION,
            &[nucleus(30)],
            &SegmentParams::default(),
        );
        assert_eq!(x, ExtraCandidates::default());
    }

    #[test]
    fn a_creaky_tail_with_no_dip_belongs_to_its_nucleus() {
        // The level falls from the voiced part straight into an unpitched bump 1 dB high: one
        // syllable (the shallow-valley rule), so no candidate.
        let e = level(
            |i| match i {
                20..=39 => -20.0,
                40..=44 => -24.0,
                45..=60 => -23.0,
                _ => -80.0,
            },
            N,
        );
        let f0 = track(|i| (20..40).contains(&i).then_some(200.0), N);
        let son = vec![0.8; N];
        let x = extra_candidates(
            &e,
            &f0,
            &son,
            &REGION,
            &[nucleus(30)],
            &SegmentParams::default(),
        );
        assert!(x.nuclei.is_empty(), "{x:?}");
    }

    #[test]
    fn a_run_holding_one_nucleus_splits_where_the_spectrum_changes() {
        // One voiced run 20..70 (no dip, no pitch break), one nucleus at 60; the sonority drops
        // from 0.95 to 0.65 at 42, as at 只猫's join.
        let e = level(|i| if (20..70).contains(&i) { -20.0 } else { -80.0 }, N);
        let f0 = track(|i| (20..70).contains(&i).then_some(250.0), N);
        let son: Vec<f32> = (0..N).map(|i| if i < 42 { 0.95 } else { 0.65 }).collect();
        let x = extra_candidates(
            &e,
            &f0,
            &son,
            &REGION,
            &[nucleus(60)],
            &SegmentParams::default(),
        );
        assert_eq!(x.boundaries, vec![42]);
        assert_eq!(frames(&x), vec![30]);
        // No change, no split; two nuclei already, no split either.
        let flat = vec![0.8; N];
        let none = ExtraCandidates::default();
        let p = SegmentParams::default();
        assert_eq!(
            extra_candidates(&e, &f0, &flat, &REGION, &[nucleus(60)], &p),
            none
        );
        let two = [nucleus(30), nucleus(60)];
        assert_eq!(extra_candidates(&e, &f0, &son, &REGION, &two, &p), none);
    }

    #[test]
    fn no_sonority_track_no_candidates() {
        let (e, f0, _) = creaky_third(0.8);
        let p = SegmentParams::default();
        assert_eq!(
            extra_candidates(&e, &f0, &[], &REGION, &[nucleus(30)], &p),
            ExtraCandidates::default()
        );
    }
}
