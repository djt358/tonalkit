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
/// pYIN's default fastest pitch change, in octaves per second.
const MAX_TRANSITION_RATE: f64 = 35.92;

/// Bins pYIN's pitch-transition kernel spans: the most whole semitones the pitch may move in one
/// hop, `round(35.92 oct/s · 12 · HOP / sr)`, in bins, plus one (41 at 16 kHz and a 160-sample
/// hop).
fn transition_width() -> f64 {
    let semitones_per_hop =
        (MAX_TRANSITION_RATE * 12.0 * HOP as f64 / f64::from(SAMPLE_RATE)).round();
    semitones_per_hop * BINS_PER_SEMITONE + 1.0
}
/// Samples the signal is advanced by before pYIN sees it (ruling R24).
///
/// The `pyin` crate mirrors librosa: the YIN template is the *first* `WIN_LENGTH` samples of each
/// frame, so with centred framing the estimate for frame `i` describes the signal around
/// `i*HOP - 256 + T/2`, where `T` is the pitch period in samples. That is about 200 samples
/// (12.5 ms, 1.3 frames) early at 150 Hz. Dropping the first `TEMPLATE_LAG` samples moves it back
/// onto `i*HOP`.
const TEMPLATE_LAG: usize = 200;

/// The built-in f0 provider: pYIN (Mauch & Dixon 2014) via the `pyin` crate, with 1024-sample
/// frames, a 160-sample hop and centred framing with zero padding.
///
/// **Timing.** pYIN's template covers only the first half of each frame, so the raw `pyin` output
/// runs about 1.3 frames (13 ms) behind the audio. `track` compensates by advancing the signal
/// 200 samples (dropping the first 200 and zero-appending 200 at the end; the frame count stays
/// `pcm.len() / HOP + 1`) before running pYIN, so frame `i` describes the signal around sample
/// `i * HOP`, in line with [`energy`](fn@crate::energy). What remains is `T/2 - 56` samples for a
/// pitch period of `T` samples: +0.28 frame at 80 Hz, 0 at 143 Hz, -0.18 frame at 300 Hz
/// (within about +-0.3 frame over 80 to 300 Hz), growing to +0.65 frame at 50 Hz.
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
        pitch_bins > transition_width()
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

        // Advance by TEMPLATE_LAG samples (see the constant): output sample `k` is input sample
        // `k + TEMPLATE_LAG`, and the tail past the end is silence. pyin panics on NaN input (a NaN
        // autocorrelation ends up as a pitch-bin index), so non-finite samples read as silence too.
        let wav: Vec<f64> = (0..pcm.len())
            .map(|k| match pcm.get(k + TEMPLATE_LAG) {
                Some(&x) if x.is_finite() => f64::from(x),
                _ => 0.0,
            })
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_transition_kernel_is_pyins_41_bins() {
        assert_eq!(transition_width(), 41.0);
    }
}
