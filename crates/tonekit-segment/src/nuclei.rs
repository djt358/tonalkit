use tonekit_core::{EnergyTrack, F0Track, FrameRange, Nucleus};

use crate::region::floor_db;
use crate::runs::{in_separate_runs, long_runs, run_of, Run, VOICING_RADIUS};
use crate::smooth::{argmax_middle, frame, local_extrema, shallow_valley, smoothed_db, Extremum};
use crate::SegmentParams;

/// Syllable nuclei inside `region`: energy peaks that are voiced, at least one per long voiced run.
///
/// A candidate is a local maximum of the 5-frame moving average of the frame dB, at or above the
/// speech threshold (p10 dB plus `p.speech_margin_db`), with periodicity at the peak: some frame
/// within 2 frames of it has `hz.is_some()` (ruling R27). `voiced_p` is deliberately not used
/// here: pYIN's `voiced_p` sags below 0.5 through fast dips and falls while its pitch estimate
/// (`hz`) stays right, and the flat energy inside a syllable makes the exact peak frame arbitrary.
/// Voicing elsewhere in the syllable is not required.
///
/// A long voiced run (ruling R58: at least 5 voiced frames, gaps of up to 2 bridged) inside the
/// region that holds no such peak adds one candidate of its own, the frame of its highest smoothed
/// dB (the middle of a flat top), if that is at or above the speech threshold and no frame within
/// 2 of it is more than `p.dip_db` louder (a run on the flank of a louder unvoiced peak is not a
/// syllable of its own). Fluent speech can run two syllables together with no dip in level at all,
/// and the voice's pitch break between them is then the only sign of the join.
///
/// A candidate within 2 frames outside a long voiced run is moved onto the run's nearest voiced
/// frame (ruling R58) if that frame is in the region and at or above the speech threshold, so a
/// nucleus lies inside the voiced part its tone is measured on even when pause or pitch-break
/// edges fall between that part and the energy peak.
///
/// Candidates are then merged left to right. A candidate joins the nucleus before it when they are
/// closer than `p.min_nucleus_gap` frames, or when the smoothed minimum between them is above
/// `min(peak_a, peak_b) - p.dip_db` and they do not lie in two different long voiced runs (each
/// within 2 frames of its run); the higher peak survives (the earlier one on a tie), and a
/// surviving new peak is compared with the nucleus before that in turn. `strength_db` is the
/// smoothed level at the nucleus minus the p10 dB.
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
    let level = Level {
        s: smoothed_db(&e.db),
        threshold: floor + p.speech_margin_db,
        start: region.start as usize,
        end: (region.end as usize).min(e.db.len()),
    };
    let runs = long_runs(f0);

    let mut candidates: Vec<usize> = voiced_peaks(&level, f0)
        .into_iter()
        .map(|c| onto_run(&level, &runs, c))
        .collect();
    for (k, run) in runs.iter().enumerate() {
        let held = candidates
            .iter()
            .any(|&c| run_of(&runs, c, VOICING_RADIUS) == Some(k));
        if !held {
            candidates.extend(run_top(&level, run, p.dip_db));
        }
    }
    candidates.sort_unstable();
    candidates.dedup();

    let mut kept: Vec<usize> = Vec::new();
    for peak in candidates {
        push_merging(&mut kept, peak, &level.s, &runs, p);
    }
    kept.into_iter()
        .map(|i| Nucleus {
            frame: frame(i),
            strength_db: level.s[i] - floor,
        })
        .collect()
}

/// The smoothed frame dB, the speech threshold, and the region's frames `start..end`.
struct Level {
    s: Vec<f32>,
    threshold: f32,
    start: usize,
    end: usize,
}

impl Level {
    /// In the region and at or above the speech threshold.
    fn speech(&self, at: usize) -> bool {
        (self.start..self.end).contains(&at) && self.s[at] >= self.threshold
    }
}

/// The local maxima of the level in the region that are speech and have a pitch within
/// [`VOICING_RADIUS`] frames (ruling R27).
fn voiced_peaks(level: &Level, f0: &F0Track) -> Vec<usize> {
    local_extrema(&level.s, level.start, level.end, Extremum::Max)
        .into_iter()
        .filter(|&peak| {
            (peak.saturating_sub(VOICING_RADIUS)..=peak + VOICING_RADIUS)
                .any(|i| f0.frames.get(i).is_some_and(|f| f.hz.is_some()))
                && level.speech(peak)
        })
        .collect()
}

/// The candidate of a long run that holds no peak (ruling R58): the loudest frame of its part of
/// the region (the middle of a flat top), if it is speech and no frame within [`VOICING_RADIUS`]
/// of it is more than `dip_db` louder.
fn run_top(level: &Level, run: &Run, dip_db: f32) -> Option<usize> {
    let (lo, hi) = (run.first.max(level.start), (run.last + 1).min(level.end));
    if lo >= hi {
        return None;
    }
    let top = argmax_middle(&level.s, lo, hi - 1);
    let around =
        &level.s[top.saturating_sub(VOICING_RADIUS)..(top + VOICING_RADIUS + 1).min(level.s.len())];
    let flank = around.iter().any(|&d| d > level.s[top] + dip_db);
    (level.speech(top) && !flank).then_some(top)
}

/// `at` moved onto the nearest frame of its long run when it lies just outside one and that frame
/// is speech (ruling R58); otherwise `at`.
fn onto_run(level: &Level, runs: &[Run], at: usize) -> usize {
    match run_of(runs, at, VOICING_RADIUS) {
        Some(k) => Some(at.clamp(runs[k].first, runs[k].last))
            .filter(|&on| level.speech(on))
            .unwrap_or(at),
        None => at,
    }
}

/// Adds `peak` (later than everything in `kept`) to `kept`, merging it into its predecessors
/// where the merge rules say so.
fn push_merging(
    kept: &mut Vec<usize>,
    mut peak: usize,
    s: &[f32],
    runs: &[Run],
    p: &SegmentParams,
) {
    while let Some(&prev) = kept.last() {
        let close = peak - prev < p.min_nucleus_gap as usize;
        let same_syllable = shallow_valley(s, prev, peak, p.dip_db)
            && !in_separate_runs(runs, prev, peak, VOICING_RADIUS);
        if !(close || same_syllable) {
            break;
        }
        kept.pop();
        if s[peak] <= s[prev] {
            peak = prev;
        }
    }
    kept.push(peak);
}
