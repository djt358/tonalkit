//! Pitch recovery (ruling R105): voiced speech pYIN leaves without a pitch.
//!
//! pYIN decides voicing with an HMM whose switch prior is strict: in a quiet or breathy recording a
//! syllable whose frames are only moderately periodic (voiced probability 0.2 to 0.5) is decoded as
//! unvoiced whole, although the signal repeats clearly at a period in the voice's range. The
//! signal says otherwise: a loud, vowel-like frame that repeats well at a lag in the voice's range
//! is voiced. Recovery runs on pYIN's track only; an external track's voicing is its own.

use tonekit_core::{F0Track, HOP, MAX_BRIDGED_GAP_FRAMES, SAMPLE_RATE};

use crate::nsdf::nsdf;

/// A recovered frame repeats at least this well (normalised square difference) at its period.
/// Voiced syllables pYIN dropped on the volunteer recordings reach 0.6 to 0.85; creak, breath,
/// fricatives and room noise stay below.
const MIN_PERIODICITY: f64 = 0.6;
/// Among the lags that repeat at least this fraction as well as the best one, the shortest (the
/// highest pitch) is the period: a voice repeats at every multiple of its period too.
const NEAR_BEST: f64 = 0.9;
/// The pitch range searched (Hz): a voice's, inside pYIN's 50 to 600 Hz, where the 512-sample
/// window still holds over 280 products at the longest lag.
const RANGE_HZ: (f64, f64) = (70.0, 500.0);
/// Consecutive recovered frames belong to one run only if their pitches are this close.
const MAX_STEP_ST: f64 = 1.5;
/// A recovered stretch is at least this many frames: the fewest a shape is measured on (a short
/// phrase-initial 一 can be voiced for only 30 to 50 ms).
const MIN_FRAMES: usize = 3;

/// Gives a pitch to every frame of a stretch of at least [`MIN_FRAMES`] (3) consecutive frames
/// that pYIN left unvoiced although each is speech (`speech[i]`), vowel-like (`vowel[i]`) and
/// periodic: its normalised square difference ([`nsdf`] over the 512 samples centred on the
/// frame) has a local maximum of at least 0.6 at a lag in the 70 to 500 Hz range, and the shortest
/// such lag within 0.9 of the best one is its period; consecutive frames of a stretch are within
/// 1.5 semitones of each other. Each lag's maximum is refined by a parabola through its
/// neighbours. Only a stretch with no pitch within 3 frames of either end is recovered: a syllable
/// pYIN lost whole, never a dropout between two of its voiced runs (the pitch break that separates
/// syllables, ruling R58, or a creak that joins them). Recovered frames keep pYIN's `voiced_p`.
///
/// `speech` and `vowel` are per frame and as long as the track; a shorter mask reads as false.
pub fn recover_pitch(track: &mut F0Track, pcm: &[f32], speech: &[bool], vowel: &[bool]) {
    let candidate = |i: usize| {
        track.frames[i].hz.is_none()
            && speech.get(i).copied().unwrap_or(false)
            && vowel.get(i).copied().unwrap_or(false)
    };
    let estimates: Vec<Option<f64>> = (0..track.frames.len())
        .map(|i| {
            if candidate(i) {
                period_hz(pcm, i * HOP)
            } else {
                None
            }
        })
        .collect();
    // Only islands: a run within a bridged gap of pYIN's own pitch would join that voiced run and
    // fill the dropout at a fast pitch change that separates two syllables (ruling R58).
    let reach = MAX_BRIDGED_GAP_FRAMES + 1;
    let pitched = |i: usize| track.frames.get(i).is_some_and(|f| f.hz.is_some());
    let islands: Vec<(usize, usize)> = runs(&estimates)
        .into_iter()
        .filter(|&(start, end)| {
            !(start.saturating_sub(reach)..start).any(pitched) && !(end..end + reach).any(pitched)
        })
        .collect();
    for (start, end) in islands {
        for (frame, hz) in track.frames[start..end]
            .iter_mut()
            .zip(&estimates[start..end])
        {
            frame.hz = hz.map(|v| v as f32);
        }
    }
}

/// The stretches `[start, end)` of consecutive estimates, each within [`MAX_STEP_ST`] of the one
/// before, at least [`MIN_FRAMES`] long.
fn runs(estimates: &[Option<f64>]) -> Vec<(usize, usize)> {
    let mut out = Vec::new();
    let mut start = 0;
    for i in 0..=estimates.len() {
        let joins = match (
            i.checked_sub(1).and_then(|p| estimates[p]),
            estimates.get(i),
        ) {
            (Some(prev), Some(Some(hz))) => (12.0 * (hz / prev).log2()).abs() <= MAX_STEP_ST,
            _ => false,
        };
        if !joins {
            if estimates.get(start).is_some_and(Option::is_some) && i - start >= MIN_FRAMES {
                out.push((start, i));
            }
            start = i;
        }
    }
    out
}

/// The pitch of `pcm` around sample `centre`, if it repeats well enough (see [`recover_pitch`]).
fn period_hz(pcm: &[f32], centre: usize) -> Option<f64> {
    let sr = f64::from(SAMPLE_RATE);
    let (lo, hi) = (
        (sr / RANGE_HZ.1).floor() as usize,
        (sr / RANGE_HZ.0).ceil() as usize,
    );
    let d: Vec<f64> = (lo - 1..=hi + 1)
        .map(|lag| nsdf(pcm, centre, lag))
        .collect();
    // Local maxima strictly inside the searched lags, as (index into d, value).
    let peaks: Vec<(usize, f64)> = (1..d.len() - 1)
        .filter(|&k| d[k] > d[k - 1] && d[k] >= d[k + 1])
        .map(|k| (k, d[k]))
        .collect();
    let best = peaks
        .iter()
        .map(|&(_, v)| v)
        .fold(f64::NEG_INFINITY, f64::max);
    if best < MIN_PERIODICITY {
        return None;
    }
    let (k, _) = *peaks.iter().find(|&&(_, v)| v >= NEAR_BEST * best)?;
    // Parabolic refinement of the peak's lag.
    let (a, b, c) = (d[k - 1], d[k], d[k + 1]);
    let denom = a - 2.0 * b + c;
    let shift = if denom < 0.0 {
        0.5 * (a - c) / denom
    } else {
        0.0
    };
    let lag = (lo - 1 + k) as f64 + shift.clamp(-0.5, 0.5);
    Some(sr / lag)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::TAU;
    use tonekit_core::F0Frame;

    /// A 1/h-harmonic voice at `hz` (harmonics below 4 kHz) with `noise` white noise relative to
    /// its peak, `n` samples.
    fn voice(hz: f64, n: usize, noise: f64) -> Vec<f32> {
        let mut state = 0x2545_F491_4F6C_DD1D_u64;
        (0..n)
            .map(|k| {
                let phase = TAU * hz * k as f64 / f64::from(SAMPLE_RATE);
                let mut acc = 0.0;
                let mut h = 1.0;
                while h * hz < 4000.0 {
                    acc += (h * phase).sin() / h;
                    h += 1.0;
                }
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                let white = state as f64 / u64::MAX as f64 - 0.5;
                (0.3 * acc + noise * white) as f32
            })
            .collect()
    }

    fn unvoiced(n: usize) -> F0Track {
        F0Track {
            frames: (0..n / HOP + 1)
                .map(|_| F0Frame {
                    hz: None,
                    voiced_p: 0.2,
                })
                .collect(),
            provider: "pyin".into(),
        }
    }

    #[test]
    fn a_periodic_vowel_left_unvoiced_gets_its_pitch() {
        for hz in [90.0, 175.0, 320.0] {
            let pcm = voice(hz, 4800, 0.2);
            let mut t = unvoiced(pcm.len());
            let all = vec![true; t.frames.len()];
            recover_pitch(&mut t, &pcm, &all, &all);
            let mid = t.frames[15].hz.expect("recovered");
            assert!((f64::from(mid) / hz - 1.0).abs() < 0.01, "{hz}: {mid}");
            assert_eq!(t.frames[15].voiced_p, 0.2);
        }
    }

    #[test]
    fn noise_consonants_and_short_stretches_stay_unvoiced() {
        // White noise has no period.
        let mut state = 0x9E37_79B9_7F4A_7C15_u64;
        let pcm: Vec<f32> = (0..4800)
            .map(|_| {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                (state as f64 / u64::MAX as f64 - 0.5) as f32
            })
            .collect();
        let mut t = unvoiced(pcm.len());
        let all = vec![true; t.frames.len()];
        recover_pitch(&mut t, &pcm, &all, &all);
        assert!(t.frames.iter().all(|f| f.hz.is_none()));
        // A periodic stretch that is not vowel-like (a consonant), or not speech, is left alone.
        let pcm = voice(175.0, 4800, 0.2);
        let none = vec![false; t.frames.len()];
        let mut t = unvoiced(pcm.len());
        recover_pitch(&mut t, &pcm, &all, &none);
        assert!(t.frames.iter().all(|f| f.hz.is_none()));
        recover_pitch(&mut t, &pcm, &none, &all);
        assert!(t.frames.iter().all(|f| f.hz.is_none()));
        // Two candidate frames are too few for a run.
        let mut t = unvoiced(pcm.len());
        let two: Vec<bool> = (0..t.frames.len()).map(|i| (10..12).contains(&i)).collect();
        recover_pitch(&mut t, &pcm, &two, &all);
        assert!(t.frames.iter().all(|f| f.hz.is_none()));
    }

    #[test]
    fn a_dropout_beside_pyins_own_pitch_is_left_alone() {
        // pYIN voiced on 0..10 and 16..: the 6-frame dropout between is periodic but stays as it
        // is, while the same frames with no pitch nearby are recovered.
        let pcm = voice(175.0, 4800, 0.2);
        let all = vec![true; pcm.len() / HOP + 1];
        let mut t = unvoiced(pcm.len());
        for (i, f) in t.frames.iter_mut().enumerate() {
            if !(10..16).contains(&i) {
                f.hz = Some(175.0);
            }
        }
        let before = t.clone();
        recover_pitch(&mut t, &pcm, &all, &all);
        assert_eq!(t, before);
        // A 12-frame dropout whose middle 6 frames are vowel-like: an island 3 frames clear of
        // the pitch on either side, recovered.
        let mut t = unvoiced(pcm.len());
        for (i, f) in t.frames.iter_mut().enumerate() {
            if !(10..22).contains(&i) {
                f.hz = Some(175.0);
            }
        }
        let middle: Vec<bool> = (0..all.len()).map(|i| (13..19).contains(&i)).collect();
        recover_pitch(&mut t, &pcm, &all, &middle);
        assert!(
            t.frames[13..19].iter().all(|f| f.hz.is_some()),
            "{:?}",
            &t.frames[10..22]
        );
        assert!(t.frames[10..13].iter().all(|f| f.hz.is_none()));
        // Two frames clear of it is not enough.
        let mut t = unvoiced(pcm.len());
        for (i, f) in t.frames.iter_mut().enumerate() {
            if !(10..22).contains(&i) {
                f.hz = Some(175.0);
            }
        }
        let near: Vec<bool> = (0..all.len()).map(|i| (12..19).contains(&i)).collect();
        recover_pitch(&mut t, &pcm, &all, &near);
        assert!(t.frames[10..22].iter().all(|f| f.hz.is_none()));
    }

    #[test]
    fn frames_pyin_voiced_are_untouched() {
        let pcm = voice(175.0, 4800, 0.2);
        let mut t = unvoiced(pcm.len());
        for f in &mut t.frames {
            f.hz = Some(123.0);
        }
        let all = vec![true; t.frames.len()];
        recover_pitch(&mut t, &pcm, &all, &all);
        assert!(t.frames.iter().all(|f| f.hz == Some(123.0)));
    }

    #[test]
    fn runs_need_three_consecutive_close_estimates() {
        let e = |v: &[f64]| {
            v.iter()
                .map(|&x| (x > 0.0).then_some(x))
                .collect::<Vec<_>>()
        };
        assert_eq!(
            runs(&e(&[0., 100., 101., 102., 101., 100., 0.])),
            vec![(1, 6)]
        );
        assert!(runs(&e(&[100., 101., 0., 102., 0., 100.])).is_empty());
        // A jump over 1.5 semitones starts a new run.
        assert!(runs(&e(&[100., 101., 120., 121.])).is_empty());
        assert_eq!(runs(&e(&[100., 101., 120., 121., 122.])), vec![(2, 5)]);
        assert_eq!(runs(&e(&[100.; 3])), vec![(0, 3)]);
    }
}
