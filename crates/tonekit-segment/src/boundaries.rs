use tonekit_core::{EnergyTrack, F0Track, FrameRange, Nucleus};

use crate::region::speech_frames;
use crate::smooth::{frame, local_extrema, smoothed_db, Extremum};
use crate::SegmentParams;

/// Boundaries at most this many frames apart count as one.
const DEDUP_FRAMES: usize = 2;
/// A span between candidates longer than this many frames (350 ms) is searched for interior
/// energy minima.
const LONG_SPAN_FRAMES: usize = 35;

/// [`boundaries_with`] under the default [`SegmentParams`].
pub fn boundaries(
    e: &EnergyTrack,
    f0: &F0Track,
    region: &FrameRange,
    nuclei: &[Nucleus],
) -> Vec<u32> {
    boundaries_with(e, f0, region, nuclei, &SegmentParams::default())
}

/// Candidate syllable boundaries for the decoder to search over: sorted frame positions, unique,
/// always including `region.start` and `region.end`, all inside the region.
///
/// Generous by design: a missing real syllable edge costs more than an extra candidate. In order
/// of priority:
///
/// 1. the region edges;
/// 2. the frame of minimum smoothed dB between each pair of adjacent `nuclei` (the middle of a
///    flat minimum);
/// 3. the edges of interior pauses (ruling R27): wherever frames turn from speech to non-speech
///    or back inside the region ([`speech_frames`](crate::speech_frames): strictly above p10 dB
///    plus `p.speech_margin_db`), the loud frame beside the crossing, i.e. the first frame of a
///    loud run entering it and the last frame leaving it.
///    That is the frame whose window straddles the syllable edge. These do not depend on
///    voicing. The steepest crossing first;
/// 4. voicing edges: the frames where `hz.is_some()` changes (the first frame of the new state;
///    ruling R32: a frame is voiced when the f0 provider gives it a pitch), the biggest change in
///    `voiced_p` across the edge first. A dip in `voiced_p` with the pitch kept is not an edge;
///    pYIN's `voiced_p` sags through fast falls and dips inside a syllable;
/// 5. interior local minima of the smoothed dB inside any span longer than 35 frames between
///    consecutive boundaries found so far, deepest (most prominent) first.
///
/// A boundary within 2 frames of a higher-priority one is dropped, and the list is capped at
/// `4 * nuclei.len() + 2` by keeping the highest priorities first, so the edges and inter-nucleus
/// minima always survive.
pub fn boundaries_with(
    e: &EnergyTrack,
    f0: &F0Track,
    region: &FrameRange,
    nuclei: &[Nucleus],
    p: &SegmentParams,
) -> Vec<u32> {
    let s = smoothed_db(&e.db);
    let (start, end) = (region.start as usize, region.end as usize);
    let cap = 4 * nuclei.len() + 2;

    // 1. Region edges: unconditional, even if the region is only a frame or two wide.
    let mut kept = vec![start];
    if end != start {
        kept.push(end);
    }
    let inside = |at: usize| start < at && at < end;

    // 2. Minimum smoothed dB between adjacent nuclei.
    let mut frames: Vec<usize> = nuclei
        .iter()
        .map(|n| n.frame as usize)
        .filter(|&f| f < s.len())
        .collect();
    frames.sort_unstable();
    frames.dedup();
    for pair in frames.windows(2) {
        let at = argmin_middle(&s, pair[0], pair[1]);
        if inside(at) {
            try_add(&mut kept, at, cap);
        }
    }

    // 3. Pause edges: the first and last frame of each run of speech frames, steepest first.
    // Frame dB is used as it stands (as for the region itself): the 5-frame average smears an
    // edge 2-3 frames into the silence, and in a short pause it would put the leaving and
    // entering crossings a frame apart.
    let speech = speech_frames(e, p);
    let db = |i: usize| e.db.get(i).copied().filter(|d| d.is_finite());
    let loud = |i: usize| speech.get(i).copied().unwrap_or(false);
    let mut edges: Vec<(usize, f32)> = (start.saturating_add(1)..end.min(e.db.len()))
        .filter(|&i| loud(i - 1) != loud(i))
        .map(|i| {
            let jump = (db(i).unwrap_or(0.0) - db(i - 1).unwrap_or(0.0)).abs();
            (if loud(i) { i } else { i - 1 }, jump)
        })
        .collect();
    edges.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    for (at, _) in edges {
        try_add(&mut kept, at, cap);
    }

    // 4. Voicing edges (R32: pitched or not), biggest voiced_p jump first (earliest first among
    // equals).
    let pitched = |i: usize| f0.frames.get(i).is_some_and(|f| f.hz.is_some());
    let voiced_p = |i: usize| f0.frames.get(i).map_or(0.0, |f| f.voiced_p);
    let mut crossings: Vec<(usize, f32)> = (start.saturating_add(1)..end.min(f0.frames.len()))
        .filter(|&i| pitched(i - 1) != pitched(i))
        .map(|i| (i, (voiced_p(i) - voiced_p(i - 1)).abs()))
        .map(|(i, jump)| (i, if jump.is_finite() { jump } else { 0.0 }))
        .collect();
    crossings.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    for (at, _) in crossings {
        try_add(&mut kept, at, cap);
    }

    // 5. Interior minima of long spans, most prominent first.
    kept.sort_unstable();
    let mut minima: Vec<(usize, f32)> = kept
        .windows(2)
        .filter(|w| w[1] - w[0] > LONG_SPAN_FRAMES)
        .flat_map(|w| local_extrema(&s, w[0] + 1, w[1], Extremum::Min))
        .map(|i| (i, prominence(&s, i)))
        .collect();
    minima.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    for (at, _) in minima {
        try_add(&mut kept, at, cap);
    }

    kept.sort_unstable();
    kept.into_iter().map(frame).collect()
}

/// Adds `at` unless the list is full or `at` is within [`DEDUP_FRAMES`] of a boundary already in it.
fn try_add(kept: &mut Vec<usize>, at: usize, cap: usize) {
    if kept.len() < cap && kept.iter().all(|&k| k.abs_diff(at) > DEDUP_FRAMES) {
        kept.push(at);
    }
}

/// The frame in `a..=b` (`b` in bounds) with the lowest `s`; for a flat minimum, the middle of its
/// first run.
fn argmin_middle(s: &[f32], a: usize, b: usize) -> usize {
    let mut best = a;
    for i in a..=b {
        if s[i] < s[best] {
            best = i;
        }
    }
    let mut last = best;
    while last < b && s[last + 1] == s[best] {
        last += 1;
    }
    (best + last) / 2
}

/// How far the minimum at `i` sits below the lower of the two hills beside it (each hill climbs
/// until `s` stops rising).
fn prominence(s: &[f32], i: usize) -> f32 {
    let mut left = i;
    while left > 0 && s[left - 1] >= s[left] {
        left -= 1;
    }
    let mut right = i;
    while right + 1 < s.len() && s[right + 1] >= s[right] {
        right += 1;
    }
    s[left].min(s[right]) - s[i]
}
