use tonekit_core::{EnergyTrack, F0Track, FrameRange, Nucleus};

use crate::region::floor_db;
use crate::smooth::{frame, local_extrema, smoothed_db, Extremum};
use crate::SegmentParams;

/// A peak is voiced if pYIN reports a pitch on any frame within this many frames of it.
const VOICING_RADIUS: usize = 2;

/// Syllable nuclei inside `region`: energy peaks that are voiced.
///
/// A candidate is a local maximum of the 5-frame moving average of the frame dB, at or above the
/// speech threshold (p10 dB plus `p.speech_margin_db`), with periodicity at the peak: some frame
/// within 2 frames of it has `hz.is_some()` (ruling R27). `voiced_p` is deliberately not used
/// here: pYIN's `voiced_p` sags below 0.5 through fast dips and falls while its pitch estimate
/// (`hz`) stays right, and the flat energy inside a syllable makes the exact peak frame arbitrary.
/// Voicing elsewhere in the syllable is not required.
///
/// Candidates are then merged left to right. A candidate joins the nucleus before it when the
/// smoothed minimum between them is above `min(peak_a, peak_b) - p.dip_db`, or when they are
/// closer than `p.min_nucleus_gap` frames; the higher peak survives (the earlier one on a tie),
/// and a surviving new peak is compared with the nucleus before that in turn. `strength_db` is the
/// smoothed peak minus the p10 dB.
///
/// The result is sorted by frame; a region that is empty or lies past the track gives no nuclei.
pub fn nuclei(
    e: &EnergyTrack,
    f0: &F0Track,
    region: &FrameRange,
    p: &SegmentParams,
) -> Vec<Nucleus> {
    let Some(floor) = floor_db(e) else {
        return Vec::new();
    };
    let threshold = floor + p.speech_margin_db;
    let s = smoothed_db(&e.db);

    let mut kept: Vec<usize> = Vec::new();
    for peak in local_extrema(
        &s,
        region.start as usize,
        region.end as usize,
        Extremum::Max,
    ) {
        let voiced = (peak.saturating_sub(VOICING_RADIUS)..=peak + VOICING_RADIUS)
            .any(|i| f0.frames.get(i).is_some_and(|f| f.hz.is_some()));
        if s[peak] >= threshold && voiced {
            push_merging(&mut kept, peak, &s, p);
        }
    }
    kept.into_iter()
        .map(|i| Nucleus {
            frame: frame(i),
            strength_db: s[i] - floor,
        })
        .collect()
}

/// Adds `peak` (later than everything in `kept`) to `kept`, merging it into its predecessors
/// where the merge rules say so.
fn push_merging(kept: &mut Vec<usize>, mut peak: usize, s: &[f32], p: &SegmentParams) {
    while let Some(&prev) = kept.last() {
        let valley = s[prev..=peak].iter().copied().fold(f32::INFINITY, f32::min);
        let shallow = valley > s[prev].min(s[peak]) - p.dip_db;
        let close = peak - prev < p.min_nucleus_gap as usize;
        if !(shallow || close) {
            break;
        }
        kept.pop();
        if s[peak] <= s[prev] {
            peak = prev;
        }
    }
    kept.push(peak);
}
