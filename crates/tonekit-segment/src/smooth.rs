//! Frame-curve helpers shared by nucleus and boundary detection.

/// Width of the energy moving average, in frames (segmentation seed).
pub(crate) const SMOOTH_FRAMES: usize = 5;
/// What a non-finite energy frame reads as: the digital-silence floor of `tonekit_f0::energy`.
const FLOOR_DB: f32 = -100.0;

/// A frame position as `u32`. Real tracks are nowhere near `u32::MAX` frames (~1.4 years), so the
/// saturation only keeps the conversion total.
pub(crate) fn frame(i: usize) -> u32 {
    u32::try_from(i).unwrap_or(u32::MAX)
}

/// Centred `SMOOTH_FRAMES`-frame moving average of `db`. The window shrinks at both ends of the
/// track (the mean of the frames that exist). Non-finite frames read as [`FLOOR_DB`].
pub(crate) fn smoothed_db(db: &[f32]) -> Vec<f32> {
    let clean: Vec<f32> = db
        .iter()
        .map(|&d| if d.is_finite() { d } else { FLOOR_DB })
        .collect();
    let half = SMOOTH_FRAMES / 2;
    (0..clean.len())
        .map(|i| {
            let window = &clean[i.saturating_sub(half)..(i + half + 1).min(clean.len())];
            window.iter().sum::<f32>() / window.len() as f32
        })
        .collect()
}

#[derive(Clone, Copy)]
pub(crate) enum Extremum {
    Max,
    Min,
}

/// Frames in `lo..hi` where `s` has a strict local extremum of the given kind: higher (or lower)
/// than both neighbours. A flat run that is higher (lower) than what surrounds it counts once, at
/// its middle frame. A run touching either end of `s` has no neighbour there, and that side counts
/// as satisfied.
pub(crate) fn local_extrema(s: &[f32], lo: usize, hi: usize, kind: Extremum) -> Vec<usize> {
    let sign = match kind {
        Extremum::Max => 1.0,
        Extremum::Min => -1.0,
    };
    let hi = hi.min(s.len());
    let mut out = Vec::new();
    let mut i = 0;
    while i < hi {
        let mut j = i;
        while j + 1 < s.len() && s[j + 1] == s[i] {
            j += 1;
        }
        let v = sign * s[i];
        let left = i == 0 || sign * s[i - 1] < v;
        let right = j + 1 == s.len() || sign * s[j + 1] < v;
        let mid = (i + j) / 2;
        if left && right && (lo..hi).contains(&mid) {
            out.push(mid);
        }
        i = j + 1;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn moving_average_is_centred_and_shrinks_at_the_ends() {
        let s = smoothed_db(&[0.0, 0.0, 10.0, 0.0, 0.0, 0.0]);
        assert_eq!(s, vec![10.0 / 3.0, 2.5, 2.0, 2.0, 2.5, 0.0]);
    }

    #[test]
    fn non_finite_frames_read_as_the_floor() {
        let s = smoothed_db(&[f32::NAN, f32::INFINITY, f32::NEG_INFINITY]);
        assert!(s.iter().all(|&d| d == FLOOR_DB));
    }

    #[test]
    fn extrema_handle_plateaus_and_ends() {
        let s = [1.0, 3.0, 3.0, 3.0, 1.0, 1.0, 2.0];
        assert_eq!(local_extrema(&s, 0, 7, Extremum::Max), vec![2, 6]);
        assert_eq!(local_extrema(&s, 0, 7, Extremum::Min), vec![0, 4]);
        assert_eq!(local_extrema(&s, 3, 6, Extremum::Max), Vec::<usize>::new());
        assert_eq!(
            local_extrema(&[5.0, 5.0, 5.0], 0, 3, Extremum::Max),
            vec![1]
        );
        assert!(local_extrema(&[], 0, 0, Extremum::Max).is_empty());
    }
}
