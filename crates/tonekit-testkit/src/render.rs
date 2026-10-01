//! The parts of rendering both generators share: the harmonic source, edge ramps, and the
//! finishing pass (noise fills, SNR noise, level, ground truth).

use std::f64::consts::PI;

use tonekit_core::HOP;

use crate::rng::Rng;
use crate::Synth;

/// Harmonics are generated while `h·f0` is below this.
const MAX_HARMONIC_HZ: f64 = 4000.0;
/// ...and f0 counts as at least this for that bound (at most 4 000 harmonics).
const MIN_HARMONIC_F0_HZ: f64 = 1.0;
/// Length of the raised-cosine ramp at each edge of a voiced stretch.
pub(crate) const RAMP_MS: f64 = 20.0;
/// Unvoiced-onset noise sigma, relative to the voiced peak.
pub(crate) const ONSET_NOISE: f64 = 0.1;
/// Creak noise sigma, relative to the voiced peak.
pub(crate) const CREAK_NOISE: f64 = 0.05;
/// Peak |x| of the finished buffer.
const OUTPUT_PEAK: f64 = 0.5;

/// Raised-cosine gain at offset `k` samples from an edge; 1 beyond the ramp.
pub(crate) fn ramp_gain(k: usize, ramp: usize) -> f64 {
    if k >= ramp {
        1.0
    } else {
        0.5 * (1.0 - (PI * k as f64 / ramp as f64).cos())
    }
}

/// `sum_{h·f0 < 4 kHz} sin(h·phase)/h`, with f0 taken as at least 1 Hz so that an absurd contour
/// (a Chao value far below the floor maps to nearly 0 Hz) cannot ask for millions of harmonics.
pub(crate) fn harmonic_sum(phase: f64, f0_hz: f64) -> f64 {
    let f0_hz = f0_hz.max(MIN_HARMONIC_F0_HZ);
    let mut acc = 0.0;
    let mut h = 1.0_f64;
    while h * f0_hz < MAX_HARMONIC_HZ {
        acc += (h * phase).sin() / h;
        h += 1.0;
    }
    acc
}

/// Samples `[start, end)` replaced by Gaussian noise with sigma `rel_sigma` times the voiced peak.
pub(crate) struct NoiseFill {
    pub start: usize,
    pub end: usize,
    pub rel_sigma: f64,
}

/// Turns a rendered harmonic layer into a [`Synth`]:
///
/// 1. the voiced peak is the largest |x| of `signal` as given (1.0 if it is all zero);
/// 2. each of `fills`, in order, replaces its samples with noise from one seeded stream;
/// 3. `snr_db: Some(s)` adds white noise to the whole buffer with RMS equal to the RMS of the
///    voiced samples (those with an f0) over `10^(s/20)`, from the same stream, if any are voiced;
/// 4. the buffer is scaled to a peak |x| of 0.5, and the f0 of sample `i·160` becomes frame `i`.
pub(crate) fn finish(
    mut signal: Vec<f64>,
    f0_at_sample: &[Option<f32>],
    fills: &[NoiseFill],
    snr_db: Option<f32>,
    seed: u64,
    syllable_frames: Vec<(u32, u32)>,
) -> Synth {
    let total = signal.len();
    let harmonic_peak = signal.iter().fold(0.0_f64, |m, x| m.max(x.abs()));
    let voiced_peak = if harmonic_peak > 0.0 {
        harmonic_peak
    } else {
        1.0
    };
    let mut rng = Rng::new(seed);
    for fill in fills {
        for x in &mut signal[fill.start..fill.end] {
            *x = fill.rel_sigma * voiced_peak * rng.gaussian();
        }
    }

    if let Some(snr_db) = snr_db {
        let (power, count) = signal
            .iter()
            .zip(f0_at_sample)
            .filter(|(_, f0)| f0.is_some())
            .fold((0.0_f64, 0_usize), |(p, c), (x, _)| (p + x * x, c + 1));
        if count > 0 {
            let sigma = (power / count as f64).sqrt() / 10.0_f64.powf(f64::from(snr_db) / 20.0);
            for x in &mut signal {
                *x += sigma * rng.gaussian();
            }
        }
    }

    let peak = signal.iter().fold(0.0_f64, |m, x| m.max(x.abs()));
    let gain = if peak > 0.0 { OUTPUT_PEAK / peak } else { 0.0 };
    let pcm: Vec<f32> = signal.iter().map(|x| (x * gain) as f32).collect();

    let f0_truth = (0..total / HOP + 1)
        .map(|frame| {
            let sample = (frame * HOP).min(total.saturating_sub(1));
            f0_at_sample.get(sample).copied().flatten()
        })
        .collect();

    Synth {
        pcm,
        f0_truth,
        syllable_frames,
    }
}
