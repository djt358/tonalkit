//! Subharmonic repair (ruling R60): a voiced frame whose signal repeats at half the tracked period
//! is really at twice the tracked pitch.
//!
//! pYIN's Viterbi path carries its pitch across short unvoiced stretches, so after a large upward
//! jump between syllables (a tone 4 ending at the floor running into a tone 1 at the ceiling, an
//! octave apart for many speakers) it can stay on the subharmonic for the whole next syllable.
//! Octave repair cannot see that: every frame of the run agrees with its neighbours. The signal
//! can: a voice at `f` repeats every `1/f`, and so also every `2/f`; when the track says `f/2`,
//! the half lag (`1/f`) is at least as periodic as the tracked one.

use tonekit_core::{F0Track, HOP, SAMPLE_RATE};

/// Samples the periodicity is measured over, centred on the frame (pYIN's autocorrelation window).
const WINDOW: usize = 512;
/// Integer lags searched on either side of a (fractional) period, in samples: pYIN's pitch is
/// quantised and a frame's pitch moves within the window.
const LAG_SLACK: usize = 2;
/// The half lag must be at least this periodic (normalised: 1 is a perfect repeat)...
const MIN_HALF_PERIODICITY: f64 = 0.5;
/// ...and at most this much less periodic than the tracked lag. A voice whose second harmonic is
/// strong repeats fairly well at half its period too, but clearly less well than at its period.
const TOLERANCE: f64 = 0.05;

/// Doubles the pitch of every voiced frame whose signal is periodic at half the tracked period
/// (ruling R60), where twice the pitch is at most `fmax_hz`.
///
/// Periodicity at lag `τ` is the normalised square-difference function
/// `2·Σ x[j]·x[j+τ] / Σ (x[j]² + x[j+τ]²)` over the `j` of the 512 samples centred on the frame
/// (sample `i·160`) whose `j+τ` is inside them too, maximised over the integer lags within 2
/// samples of `τ`. A frame is doubled when that measure at half its period is at least 0.5 and at
/// least the measure at its full period minus 0.05. `voiced_p` is unchanged. Run
/// [`repair_octaves`](crate::repair_octaves) afterwards for the frames this leaves isolated.
pub fn repair_subharmonics(track: &mut F0Track, pcm: &[f32], fmax_hz: f32) {
    let sr = f64::from(SAMPLE_RATE);
    for (i, frame) in track.frames.iter_mut().enumerate() {
        let Some(hz) = frame.hz else { continue };
        if !(hz.is_finite() && hz > 0.0) || 2.0 * hz > fmax_hz {
            continue;
        }
        let period = sr / f64::from(hz);
        let centre = i * HOP;
        let full = periodicity(pcm, centre, period);
        let half = periodicity(pcm, centre, period / 2.0);
        if half >= MIN_HALF_PERIODICITY && half >= full - TOLERANCE {
            frame.hz = Some(2.0 * hz);
        }
    }
}

/// The best normalised square-difference periodicity of `pcm` around sample `centre` over the
/// integer lags within [`LAG_SLACK`] of `period` (at least 1); 0 where there is no signal.
fn periodicity(pcm: &[f32], centre: usize, period: f64) -> f64 {
    let nearest = period.round().max(1.0) as usize;
    let lo = nearest.saturating_sub(LAG_SLACK).max(1);
    (lo..=nearest + LAG_SLACK)
        .map(|lag| nsdf(pcm, centre, lag))
        .fold(0.0, f64::max)
}

/// `2·Σ x[j]·x[j+lag] / Σ (x[j]² + x[j+lag]²)` over the window centred on `centre`, clamped to
/// `pcm`; 0 if the window holds no pair or no energy. Non-finite samples read as silence.
fn nsdf(pcm: &[f32], centre: usize, lag: usize) -> f64 {
    let start = centre.saturating_sub(WINDOW / 2);
    let end = (centre + WINDOW / 2).min(pcm.len());
    if end < start + lag + 1 {
        return 0.0;
    }
    let x = |k: usize| {
        let v = f64::from(pcm[k]);
        if v.is_finite() {
            v
        } else {
            0.0
        }
    };
    let (mut cross, mut power) = (0.0_f64, 0.0_f64);
    for j in start..end - lag {
        let (a, b) = (x(j), x(j + lag));
        cross += a * b;
        power += a * a + b * b;
    }
    if power > 0.0 {
        2.0 * cross / power
    } else {
        0.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::TAU;
    use tonekit_core::F0Frame;

    /// `seconds` of a 1/h-harmonic voice at `hz` (harmonics below 4 kHz).
    fn voice(hz: f64, seconds: f64) -> Vec<f32> {
        let n = (seconds * f64::from(SAMPLE_RATE)) as usize;
        (0..n)
            .map(|k| {
                let phase = TAU * hz * k as f64 / f64::from(SAMPLE_RATE);
                let mut acc = 0.0;
                let mut h = 1.0;
                while h * hz < 4000.0 {
                    acc += (h * phase).sin() / h;
                    h += 1.0;
                }
                (0.3 * acc) as f32
            })
            .collect()
    }

    fn tracked(pcm: &[f32], hz: f32) -> F0Track {
        F0Track {
            frames: (0..pcm.len() / HOP + 1)
                .map(|_| F0Frame {
                    hz: Some(hz),
                    voiced_p: 0.9,
                })
                .collect(),
            provider: "test".into(),
        }
    }

    fn middle(t: &F0Track) -> Option<f32> {
        t.frames[t.frames.len() / 2].hz
    }

    #[test]
    fn a_track_on_the_subharmonic_is_doubled() {
        let pcm = voice(260.0, 0.3);
        let mut t = tracked(&pcm, 130.0);
        repair_subharmonics(&mut t, &pcm, 600.0);
        assert_eq!(middle(&t), Some(260.0));
    }

    #[test]
    fn a_right_track_is_left_alone() {
        for hz in [85.0, 130.0, 260.0, 330.0] {
            let pcm = voice(hz, 0.3);
            let mut t = tracked(&pcm, hz as f32);
            repair_subharmonics(&mut t, &pcm, 600.0);
            assert!(t.frames.iter().all(|f| f.hz == Some(hz as f32)), "{hz} Hz");
        }
    }

    #[test]
    fn a_strong_second_harmonic_is_not_mistaken_for_the_fundamental() {
        // H2 at twice the amplitude of H1: it repeats at half the period at 0.6, clearly below
        // the full period's 1.0.
        let n = 4800;
        let pcm: Vec<f32> = (0..n)
            .map(|k| {
                let phase = TAU * 120.0 * k as f64 / f64::from(SAMPLE_RATE);
                (0.1 * phase.sin() + 0.2 * (2.0 * phase).sin()) as f32
            })
            .collect();
        let mut t = tracked(&pcm, 120.0);
        repair_subharmonics(&mut t, &pcm, 600.0);
        assert_eq!(middle(&t), Some(120.0));
    }

    #[test]
    fn doubling_never_leaves_the_search_range_and_skips_unvoiced_frames() {
        let pcm = voice(500.0, 0.3);
        let mut t = tracked(&pcm, 250.0);
        repair_subharmonics(&mut t, &pcm, 450.0);
        assert_eq!(middle(&t), Some(250.0));
        let mut t = tracked(&pcm, 250.0);
        t.frames.iter_mut().for_each(|f| f.hz = None);
        repair_subharmonics(&mut t, &pcm, 600.0);
        assert!(t.frames.iter().all(|f| f.hz.is_none()));
    }

    #[test]
    fn silence_and_noise_like_input_are_left_alone() {
        let silent = vec![0.0_f32; 4800];
        let mut t = tracked(&silent, 150.0);
        repair_subharmonics(&mut t, &silent, 600.0);
        assert!(t.frames.iter().all(|f| f.hz == Some(150.0)));
        let mut weird = vec![f32::NAN; 4800];
        weird[100] = 1.0;
        let mut t = tracked(&weird, 150.0);
        repair_subharmonics(&mut t, &weird, 600.0);
        assert!(t.frames.iter().all(|f| f.hz == Some(150.0)));
    }
}
