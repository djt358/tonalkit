//! Creak is not a pitch (ruling R105): pYIN reports a pitch just above its floor on creaky voice,
//! whose pulses are irregular and far apart, and in a quiet recording on the noise between
//! syllables. Such a pitch is no tone evidence: a syllable whose end is tracked at 50-60 Hz
//! measures as a fall several Chao below its register. The frame is left unpitched, so the
//! syllable is judged as an unpitched one (ruling R103) or on the rest of its pitch.

use tonekit_core::{F0Track, HOP, SAMPLE_RATE};

use crate::nsdf::nsdf;

/// Pitches below this (Hz) are checked: pYIN's 50 Hz floor plus about 6 semitones, under every
/// voice's modal range.
const NEAR_FLOOR_HZ: f32 = 70.0;
/// A checked frame keeps its pitch only if the signal repeats at least this well at its period
/// (best of the integer lags within 2 samples of it): a voice's low notes do, creak and noise do
/// not.
const MIN_PERIODICITY: f64 = 0.5;
/// Integer lags searched on either side of the period.
const LAG_SLACK: usize = 2;

/// Removes the pitch of every frame of pYIN's `track` under 70 Hz at which `pcm` repeats less
/// well than 0.5 (normalised square difference over the 512 samples centred on the frame, best of
/// the lags within 2 samples of the period). `voiced_p` is unchanged.
pub fn unpitch_creak(track: &mut F0Track, pcm: &[f32]) {
    let sr = f64::from(SAMPLE_RATE);
    for (i, frame) in track.frames.iter_mut().enumerate() {
        let Some(hz) = frame.hz else { continue };
        if !(hz.is_finite() && hz > 0.0) || hz >= NEAR_FLOOR_HZ {
            continue;
        }
        let period = (sr / f64::from(hz)).round() as usize;
        let best = (period.saturating_sub(LAG_SLACK).max(1)..=period + LAG_SLACK)
            .map(|lag| nsdf(pcm, i * HOP, lag))
            .fold(0.0, f64::max);
        if best < MIN_PERIODICITY {
            frame.hz = None;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::TAU;
    use tonekit_core::F0Frame;

    fn tracked(n: usize, hz: f32) -> F0Track {
        F0Track {
            frames: (0..n / HOP + 1)
                .map(|_| F0Frame {
                    hz: Some(hz),
                    voiced_p: 0.3,
                })
                .collect(),
            provider: "pyin".into(),
        }
    }

    fn sine(hz: f64, n: usize) -> Vec<f32> {
        (0..n)
            .map(|k| (0.3 * (TAU * hz * k as f64 / f64::from(SAMPLE_RATE)).sin()) as f32)
            .collect()
    }

    #[test]
    fn a_low_pitch_the_signal_does_not_repeat_at_is_removed() {
        let mut state = 0x9E37_79B9_7F4A_7C15_u64;
        let noise: Vec<f32> = (0..4800)
            .map(|_| {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                (state as f64 / u64::MAX as f64 - 0.5) as f32
            })
            .collect();
        let mut t = tracked(noise.len(), 53.0);
        unpitch_creak(&mut t, &noise);
        assert!(t.frames.iter().all(|f| f.hz.is_none() && f.voiced_p == 0.3));
    }

    #[test]
    fn a_low_voice_that_repeats_keeps_its_pitch_and_higher_pitches_are_not_checked() {
        let low = sine(60.0, 4800);
        let mut t = tracked(low.len(), 60.0);
        unpitch_creak(&mut t, &low);
        assert!(t.frames[5..25].iter().all(|f| f.hz == Some(60.0)));
        // At 70 Hz and above nothing is checked, even on noise-like input.
        let silent = vec![0.0; 4800];
        let mut t = tracked(silent.len(), 70.0);
        unpitch_creak(&mut t, &silent);
        assert!(t.frames.iter().all(|f| f.hz == Some(70.0)));
    }
}
