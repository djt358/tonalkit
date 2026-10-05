//! How vowel-like each frame's spectrum is (ruling R102): the share of its energy that lies in the
//! band of the low formants.
//!
//! Vowels, nasals, glides and other sonorants carry most of their energy between about 150 Hz and
//! 2 kHz (the low harmonics and the first formant, and the second of back and open vowels),
//! whether or not a pitch tracker can follow their voice: creaky and breathy vowels included.
//! Fricatives (s, sh, x) carry theirs above 2 kHz, and room rumble lies below 150 Hz. So a frame that is loud, unpitched and
//! sonorant is a syllable whose pitch was lost, not a consonant or silence.

use std::f64::consts::{FRAC_1_SQRT_2, PI};

use tonekit_core::SAMPLE_RATE;

use crate::energy::{finite_or_silence, frame_power};

/// Energy below this is rumble, not voice (Hz).
const BAND_LOW_HZ: f64 = 150.0;
/// The top of the low-formant band (Hz). At 1 kHz a high voice's open vowels (F1 near 1 kHz)
/// read as low as fricatives; at 2 kHz the volunteer recordings' unpitched speech frames split
/// cleanly into fricatives (under 0.2) and vowels (over 0.5).
const BAND_HIGH_HZ: f64 = 2000.0;

/// A second-order Butterworth section (bilinear transform, Q = 1/√2), direct form I.
struct Biquad {
    b: [f64; 3],
    a: [f64; 2],
}

impl Biquad {
    /// `high`: a high-pass at `hz`; otherwise a low-pass.
    fn butterworth(hz: f64, high: bool) -> Biquad {
        let w0 = 2.0 * PI * hz / f64::from(SAMPLE_RATE);
        let (sin, cos) = w0.sin_cos();
        let alpha = sin / (2.0 * FRAC_1_SQRT_2);
        let a0 = 1.0 + alpha;
        let (b0, b1) = if high {
            ((1.0 + cos) / 2.0, -(1.0 + cos))
        } else {
            ((1.0 - cos) / 2.0, 1.0 - cos)
        };
        Biquad {
            b: [b0 / a0, b1 / a0, b0 / a0],
            a: [-2.0 * cos / a0, (1.0 - alpha) / a0],
        }
    }

    /// `x` filtered, starting from rest.
    fn run(&self, x: &[f64]) -> Vec<f64> {
        let (mut x1, mut x2, mut y1, mut y2) = (0.0, 0.0, 0.0, 0.0);
        x.iter()
            .map(|&x0| {
                let y0 = self.b[0] * x0 + self.b[1] * x1 + self.b[2] * x2
                    - self.a[0] * y1
                    - self.a[1] * y2;
                (x2, x1, y2, y1) = (x1, x0, y1, y0);
                y0
            })
            .collect()
    }
}

/// Per frame, the share (0 to 1) of the signal's energy above 150 Hz that lies below 2 kHz, over
/// the 25 ms Hann window of [`energy`](crate::energy) centred on each hop (`pcm.len() / HOP + 1`
/// frames).
///
/// The signal is high-passed at 150 Hz (a second-order Butterworth section), and that is the
/// reference; it is then low-passed at 2 kHz (two sections, fourth order) for the band. A frame
/// with no energy above 150 Hz reads 0. Non-finite samples count as silence. A vowel reads about
/// 0.5 to 1, a fricative under 0.2 and white noise about 0.24 (the band's share of the spectrum), a fricative or white noise under 0.2.
pub fn sonority(pcm: &[f32]) -> Vec<f32> {
    let x: Vec<f64> = pcm.iter().map(|&v| finite_or_silence(v)).collect();
    let high = Biquad::butterworth(BAND_LOW_HZ, true).run(&x);
    let low = Biquad::butterworth(BAND_HIGH_HZ, false);
    let band = low.run(&low.run(&high));
    frame_power(&band)
        .into_iter()
        .zip(frame_power(&high))
        .map(|(b, h)| {
            if h > 0.0 && h.is_finite() {
                (b / h).clamp(0.0, 1.0) as f32
            } else {
                0.0
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::f64::consts::TAU;
    use tonekit_core::HOP;

    fn tone(hz: f64, n: usize) -> Vec<f32> {
        (0..n)
            .map(|k| (0.3 * (TAU * hz * k as f64 / f64::from(SAMPLE_RATE)).sin()) as f32)
            .collect()
    }

    fn middle(s: &[f32]) -> f32 {
        s[s.len() / 2]
    }

    #[test]
    fn one_value_per_frame() {
        assert_eq!(sonority(&tone(500.0, 4800)).len(), 4800 / HOP + 1);
        assert_eq!(sonority(&[]).len(), 1);
    }

    #[test]
    fn the_first_formant_band_reads_high_and_fricative_frequencies_low() {
        assert!(middle(&sonority(&tone(500.0, 8000))) > 0.95);
        assert!(middle(&sonority(&tone(1000.0, 8000))) > 0.85);
        assert!(middle(&sonority(&tone(5000.0, 8000))) < 0.05);
        // Each low-pass section is 3 dB down at the edge: a quarter of the power passes.
        let edge = middle(&sonority(&tone(2000.0, 8000)));
        assert!((0.15..0.35).contains(&edge), "{edge}");
    }

    #[test]
    fn white_noise_is_not_sonorant() {
        let mut state = 0x9E37_79B9_7F4A_7C15_u64;
        let noise: Vec<f32> = (0..16000)
            .map(|_| {
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                (state as f64 / u64::MAX as f64 - 0.5) as f32
            })
            .collect();
        let s = sonority(&noise);
        let mean = s[5..s.len() - 5].iter().sum::<f32>() / (s.len() - 10) as f32;
        assert!((0.15..0.35).contains(&mean), "{mean}");
    }

    #[test]
    fn silence_and_non_finite_samples_read_zero() {
        assert!(sonority(&[0.0; 3200]).iter().all(|&v| v == 0.0));
        assert!(sonority(&[f32::NAN; 3200]).iter().all(|&v| v == 0.0));
    }
}
