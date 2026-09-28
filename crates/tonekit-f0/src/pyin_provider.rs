use pyin::{Framing, PYINExecutor, PadMode};
use tonekit_core::{F0Frame, F0Track, HOP, SAMPLE_RATE};

use crate::provider::{fit_length, F0Provider};

/// pYIN frame length in samples (64 ms at 16 kHz).
const FRAME_LENGTH: usize = 1024;
/// pYIN's own default autocorrelation window (`frame_length / 2`); it bounds the longest lag
/// the search can reach at `FRAME_LENGTH - WIN_LENGTH - 1` samples.
const WIN_LENGTH: usize = FRAME_LENGTH / 2;
/// Pitch-bin resolution is pYIN's default of 10 bins per semitone.
const BINS_PER_SEMITONE: f64 = 10.0;
/// Bins pYIN's pitch-transition kernel spans: `round(35.92 oct/s * 12 * HOP / sr) * 10 + 1`.
const TRANSITION_WIDTH: usize = 41;

/// The built-in f0 provider: pYIN (Mauch & Dixon 2014) via the `pyin` crate, with 1024-sample
/// frames, a 160-sample hop and zero padding at both ends so frame `i` is centred on `i * HOP`.
///
/// `fmin`/`fmax` bound the search range in Hz. A range `pyin` cannot run (see
/// [`Pyin::range_supported`]) yields an all-unvoiced track instead of a panic.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Pyin {
    pub fmin: f32,
    pub fmax: f32,
}

impl Default for Pyin {
    /// 50 to 600 Hz: covers low creaky male voices up to high female and child voices.
    fn default() -> Self {
        Self {
            fmin: 50.0,
            fmax: 600.0,
        }
    }
}

impl Pyin {
    /// Whether `pyin` can search `fmin..=fmax` at 16 kHz with this frame configuration.
    ///
    /// The `pyin` crate asserts on unsupported ranges, and a library that ends up behind an FFI
    /// boundary must not panic on a caller's numbers. The conditions mirror those asserts:
    /// `0 < fmin < fmax <= 8 kHz`; the longest lag (`16 kHz / fmin`) must fit the autocorrelation
    /// window (which also puts a floor of about 31 Hz on `fmin`, below which `pyin` would silently
    /// search a narrower range than asked); the lag range must span at least two samples; and the
    /// pitch range must span more bins than the transition kernel is wide (about 1.26 : 1).
    pub fn range_supported(&self) -> bool {
        let (fmin, fmax) = (f64::from(self.fmin), f64::from(self.fmax));
        let sr = f64::from(SAMPLE_RATE);
        if !(fmin > 0.0 && fmin < fmax && fmax <= sr / 2.0) {
            return false; // also rejects NaN and infinities
        }
        let longest_lag = (sr / fmin).ceil();
        if longest_lag > (FRAME_LENGTH - WIN_LENGTH - 1) as f64 {
            return false;
        }
        let shortest_lag = (sr / fmax).floor().max(1.0);
        if longest_lag < shortest_lag + 2.0 {
            return false;
        }
        let pitch_bins = (12.0 * BINS_PER_SEMITONE * (fmax / fmin).log2()).floor() + 1.0;
        pitch_bins > TRANSITION_WIDTH as f64
    }
}

impl F0Provider for Pyin {
    fn name(&self) -> &str {
        "pyin"
    }

    fn track(&self, pcm: &[f32]) -> F0Track {
        let n_frames = pcm.len() / HOP + 1;
        let mut track = F0Track {
            provider: self.name().to_owned(),
            frames: Vec::new(),
        };
        if !self.range_supported() {
            return fit_length(track, n_frames);
        }

        // pyin panics on NaN input (a NaN autocorrelation ends up as a pitch-bin index), so
        // non-finite samples read as silence.
        let wav: Vec<f64> = pcm
            .iter()
            .map(|&x| if x.is_finite() { f64::from(x) } else { 0.0 })
            .collect();
        let mut executor = PYINExecutor::<f64>::new(
            f64::from(self.fmin),
            f64::from(self.fmax),
            SAMPLE_RATE,
            FRAME_LENGTH,
            None,
            Some(HOP),
            None,
        );
        let (_seconds, f0, voiced_flag, voiced_prob) =
            executor.pyin(&wav, f64::NAN, Framing::Center(PadMode::Constant(0.0)));

        track.frames = f0
            .iter()
            .zip(&voiced_flag)
            .zip(&voiced_prob)
            .map(|((&hz, &voiced), &p)| F0Frame {
                hz: (voiced && hz.is_finite()).then_some(hz as f32),
                voiced_p: if p.is_finite() { p as f32 } else { 0.0 },
            })
            .collect();
        // Centred framing already gives `pcm.len() / HOP + 1` frames; this only guards the count.
        fit_length(track, n_frames)
    }
}
