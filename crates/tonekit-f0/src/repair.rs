use tonekit_core::F0Track;

/// Voiced neighbours consulted on each side of a frame.
const NEIGHBOURS: usize = 5;
/// A frame further than this from its neighbours' median is an octave error, in semitones.
const MAX_DEVIATION_ST: f32 = 9.0;
/// Semitone reference (spec §6.2).
const REF_HZ: f32 = 55.0;
/// Unvoiced gaps of at most this many frames do not end a voiced run (ruling R32).
const MAX_BRIDGED_GAP: usize = 2;
/// Runs with fewer voiced frames than this are left alone (ruling R32).
const MIN_RUN_FRAMES: usize = 5;

/// Fix isolated octave jumps in place, one voiced run at a time (ruling R32).
///
/// A voiced frame is one with a pitch (`hz.is_some()`, a positive finite number): the provider's
/// own voicing decision. `voiced_p` plays no part here. A *voiced run* is a maximal stretch of
/// voiced frames in which no two consecutive voiced frames are more than 2 unvoiced frames apart,
/// roughly one syllable's voiced part; a run of fewer than 5 voiced frames is left alone.
///
/// Within a run, take the median semitone (re 55 Hz) of up to 5 voiced neighbours on each side,
/// the nearest voiced frames of the same run with unvoiced ones skipped and the frame itself
/// excluded. If the frame is more than 9 st from that median it is shifted 12 st (halved or
/// doubled) toward it. One pass, with every median taken from the original values, so a wrong
/// frame cannot drag its neighbours after it.
///
/// Keeping the median inside the run means a neighbouring syllable's pitch never votes: a low
/// syllable followed by a high one after a pause is two runs, and neither is pulled toward the
/// other.
pub fn repair_octaves(track: &mut F0Track) {
    let voiced: Vec<(usize, f32)> = track
        .frames
        .iter()
        .enumerate()
        .filter_map(|(i, f)| match f.hz {
            Some(hz) if hz.is_finite() && hz > 0.0 => Some((i, 12.0 * (hz / REF_HZ).log2())),
            _ => None,
        })
        .collect();

    let mut start = 0;
    for end in 1..=voiced.len() {
        let run_ends =
            end == voiced.len() || voiced[end].0 - voiced[end - 1].0 > MAX_BRIDGED_GAP + 1;
        if run_ends {
            repair_run(track, &voiced[start..end]);
            start = end;
        }
    }
}

/// Repairs the frames of one voiced run, `(frame, semitones)` in frame order.
fn repair_run(track: &mut F0Track, run: &[(usize, f32)]) {
    if run.len() < MIN_RUN_FRAMES {
        return;
    }
    let mut around = Vec::with_capacity(2 * NEIGHBOURS);
    for (pos, &(frame, st)) in run.iter().enumerate() {
        around.clear();
        around.extend(
            run[pos.saturating_sub(NEIGHBOURS)..pos]
                .iter()
                .map(|&(_, s)| s),
        );
        around.extend(
            run[pos + 1..(pos + 1 + NEIGHBOURS).min(run.len())]
                .iter()
                .map(|&(_, s)| s),
        );
        let deviation = st - median(&mut around);
        if deviation.abs() > MAX_DEVIATION_ST {
            if let Some(hz) = track.frames[frame].hz.as_mut() {
                // +-12 st is exactly a factor of two.
                *hz *= if deviation > 0.0 { 0.5 } else { 2.0 };
            }
        }
    }
}

/// Median of a non-empty slice of finite values (mean of the middle pair when even).
fn median(values: &mut [f32]) -> f32 {
    values.sort_by(f32::total_cmp);
    let mid = values.len() / 2;
    if values.len() % 2 == 1 {
        values[mid]
    } else {
        0.5 * (values[mid - 1] + values[mid])
    }
}
