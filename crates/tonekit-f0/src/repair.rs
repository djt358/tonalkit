use tonekit_core::F0Track;

/// Voiced neighbours consulted on each side of a frame.
const NEIGHBOURS: usize = 5;
/// A frame further than this from its neighbours' median is an octave error, in semitones.
const MAX_DEVIATION_ST: f32 = 9.0;
/// Semitone reference (spec §6.2).
const REF_HZ: f32 = 55.0;

/// Fix isolated octave jumps in place.
///
/// For every voiced frame (`hz.is_some() && voiced_p >= 0.5`), take the median semitone (re 55 Hz)
/// of up to 5 voiced neighbours on each side, the nearest voiced frames with unvoiced ones
/// skipped and the frame itself excluded. If the frame is more than 9 st from that median it is
/// shifted 12 st (halved or doubled) toward it. One pass, with every median taken from the
/// original values, so a wrong frame cannot drag its neighbours after it. A voiced frame with
/// no voiced neighbour is left alone, and so are unvoiced frames.
pub fn repair_octaves(track: &mut F0Track) {
    let voiced: Vec<(usize, f32)> = track
        .frames
        .iter()
        .enumerate()
        .filter_map(|(i, f)| match f.hz {
            Some(hz) if f.voiced_p >= 0.5 && hz.is_finite() && hz > 0.0 => {
                Some((i, 12.0 * (hz / REF_HZ).log2()))
            }
            _ => None,
        })
        .collect();

    let mut around = Vec::with_capacity(2 * NEIGHBOURS);
    for (pos, &(frame, st)) in voiced.iter().enumerate() {
        around.clear();
        around.extend(
            voiced[pos.saturating_sub(NEIGHBOURS)..pos]
                .iter()
                .map(|&(_, s)| s),
        );
        around.extend(
            voiced[pos + 1..(pos + 1 + NEIGHBOURS).min(voiced.len())]
                .iter()
                .map(|&(_, s)| s),
        );
        if around.is_empty() {
            continue;
        }
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
