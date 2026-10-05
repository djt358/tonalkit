//! A second syllable inside one voiced run (ruling R102): two syllables joined by a sonorant
//! (只猫 zhī māo) can run with no dip in level and no break in pitch, so they hold one nucleus,
//! but the spectrum changes at the join.

/// The sonority must change by at least this much across a split (the mean of the 2 frames from
/// it against the 2 before it).
const SPLIT_CHANGE: f32 = 0.2;
/// Sonority is averaged over this many frames on either side of a candidate split.
const SPLIT_REACH: usize = 2;
/// Each part of a split run is at least this many frames (60 ms, the shortest syllable).
pub(crate) const MIN_PART: usize = 6;
/// A split is at least this many frames from the nucleus the run holds.
const SPLIT_FROM_NUCLEUS: usize = 3;

/// Where the voiced run `a..=b` holding the nucleus at `nucleus` splits into two syllables: the
/// first frame of the second part, at the frame where the sonority changes most, if that change
/// is at least 0.2, both parts are at least [`MIN_PART`] frames and the split is at least 3 frames
/// from the nucleus (the later frame on a tie).
pub(crate) fn split(sonority: &[f32], a: usize, b: usize, nucleus: usize) -> Option<usize> {
    let mean = |from: usize, to: usize| sonority[from..to].iter().sum::<f32>() / (to - from) as f32;
    let lo = a + MIN_PART.max(SPLIT_REACH);
    let hi = (b + 1).checked_sub(MIN_PART.max(SPLIT_REACH))?;
    (lo..=hi)
        .filter(|&k| k.abs_diff(nucleus) >= SPLIT_FROM_NUCLEUS)
        .map(|k| {
            (
                k,
                (mean(k, k + SPLIT_REACH) - mean(k - SPLIT_REACH, k)).abs(),
            )
        })
        .filter(|&(_, change)| change >= SPLIT_CHANGE)
        .max_by(|x, y| x.1.total_cmp(&y.1).then(x.0.cmp(&y.0)))
        .map(|(k, _)| k)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_split_is_where_the_sonority_changes_most() {
        let son: Vec<f32> = (0..60).map(|i| if i < 30 { 0.9 } else { 0.6 }).collect();
        assert_eq!(split(&son, 10, 50, 45), Some(30));
        // Too close to the nucleus, or to an end of the run.
        assert_eq!(split(&son, 10, 50, 31), None);
        assert_eq!(split(&son, 26, 50, 45), None);
        // Too small a change.
        let son: Vec<f32> = (0..60).map(|i| if i < 30 { 0.9 } else { 0.75 }).collect();
        assert_eq!(split(&son, 10, 50, 45), None);
        // A run too short for two parts.
        assert_eq!(split(&son, 10, 18, 12), None);
    }
}
